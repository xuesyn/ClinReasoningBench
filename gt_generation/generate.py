"""
Ground Truth Generation CLI for ClinReasonBench.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gt_generation.processor import GTProcessor, validate_input_sample
from gt_generation.resume import load_done_status, merge_records, should_skip_record

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_input_data(path: str) -> list:
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return data


def resolve_mode(mode: str, two_step_flag: bool) -> str:
    if two_step_flag:
        return "two-step"
    return mode


def main():
    parser = argparse.ArgumentParser(description="Generate ground truth for ClinReasonBench")
    parser.add_argument("--input", "-i", required=True, help="Input patient data JSONL")
    parser.add_argument("--graph", "-g", required=True, help="Graph definition JSON")
    parser.add_argument("--guidance", required=True, help="Guidance JSONL (reference knowledge)")
    parser.add_argument("--disease-type", "-t", choices=["cancer", "emergency"], required=True)
    parser.add_argument("--output", "-o", required=True, help="Output GT JSONL path")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", ""),
        help="LLM API key (or set OPENAI_API_KEY env var)",
    )
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="LLM API base URL")
    parser.add_argument("--model", default="gpt-4o", help="Generation model name")
    parser.add_argument("--tag-model", default="", help="Optional separate model for the tagging stage")
    parser.add_argument("--language", "-l", choices=["en", "zh"], default="en")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers")
    parser.add_argument("--save-interval", type=int, default=10, help="Flush merged output every N samples")
    parser.add_argument("--guideline-name", default="", help="Guideline name for prompt")
    parser.add_argument("--disease-domain", default="", help="Clinical domain description for prompt")
    parser.add_argument("--example", default=None, help="Path to few-shot example JSON")
    parser.add_argument("--extra-treatments", default=None, help="Comma-separated extra treatments to add")
    parser.add_argument("--max-retries", type=int, default=3, help="Max API retries per LLM call")
    parser.add_argument("--max-parse-retries", type=int, default=5, help="Max parse retries per generation stage")
    parser.add_argument(
        "--mode",
        choices=["one-step", "two-step"],
        default="one-step",
        help="Generation mode. one-step returns tagged reasoning directly, two-step adds tags in a second call.",
    )
    parser.add_argument(
        "--two-step",
        action="store_true",
        help="Deprecated alias for --mode two-step. Kept for backward compatibility.",
    )
    parser.add_argument(
        "--resume-policy",
        choices=["qc-pass-only", "uuid-exists", "force-rerun"],
        default="qc-pass-only",
        help="Skip policy for existing output records.",
    )
    parser.add_argument(
        "--no-strict-schema",
        action="store_true",
        help="Disable strict schema validation. Not recommended for production GT generation.",
    )
    parser.add_argument(
        "--no-debug-fields",
        action="store_true",
        help="Drop extra debug fields from the final output.",
    )
    parser.add_argument(
        "--disable-seer-qc",
        action="store_true",
        help="Disable SEER-based QC conflict checks.",
    )
    args = parser.parse_args()

    if not args.api_key:
        logger.error("API key required. Use --api-key or set OPENAI_API_KEY env var.")
        sys.exit(1)

    mode = resolve_mode(args.mode, args.two_step)
    extra_treatments = None
    if args.extra_treatments:
        extra_treatments = [item.strip() for item in args.extra_treatments.split(",") if item.strip()]

    processor = GTProcessor(
        graph_path=args.graph,
        guidance_path=args.guidance,
        disease_type=args.disease_type,
        language=args.language,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        tag_model=args.tag_model or None,
        guideline_name=args.guideline_name,
        disease_domain=args.disease_domain,
        extra_treatments=extra_treatments,
        example_path=args.example,
        max_retries=args.max_retries,
        max_parse_retries=args.max_parse_retries,
        mode=mode,
        strict_schema=not args.no_strict_schema,
        keep_debug_fields=not args.no_debug_fields,
        enable_seer_qc=not args.disable_seer_qc,
    )

    logger.info(f"Loaded graph: {len(processor.treatments)} treatments")
    logger.info(f"Treatments: {processor.treatments}")
    logger.info(
        "Disease type: %s, Language: %s, Mode: %s, Resume policy: %s",
        args.disease_type,
        args.language,
        mode,
        args.resume_policy,
    )

    all_samples = load_input_data(args.input)
    logger.info(f"Loaded {len(all_samples)} input samples")
    if all_samples:
        validate_input_sample(all_samples[0], args.disease_type, sample_index=0)

    existing_status = load_done_status(args.output)
    logger.info(f"Found {len(existing_status)} existing result records")

    to_process = []
    for sample in all_samples:
        record = existing_status.get(sample.get("uuid"))
        if should_skip_record(record, args.resume_policy):
            continue
        to_process.append(sample)
    logger.info(f"Samples to process: {len(to_process)}")

    if not to_process:
        logger.info("Nothing to process.")
        return

    batch_buffer = []
    completed = 0
    errors = 0

    def flush_buffer():
        nonlocal batch_buffer
        if not batch_buffer:
            return
        merge_records(args.output, batch_buffer)
        batch_buffer = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(processor.process_single, sample): sample for sample in to_process}
        with tqdm(total=len(to_process), desc="Generating GT") as pbar:
            for future in as_completed(futures):
                try:
                    result = future.result()
                    batch_buffer.append(result)
                    completed += 1

                    has_error = any(result.get(field) for field in ("think_error", "tag_error", "check_error"))
                    if has_error:
                        errors += 1
                        logger.warning(
                            "QC issue for %s | think_error=%s | tag_error=%s | check_error=%s",
                            result.get("uuid"),
                            result.get("think_error", ""),
                            result.get("tag_error", ""),
                            result.get("check_error", ""),
                        )

                    if len(batch_buffer) >= args.save_interval:
                        flush_buffer()
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    logger.error(f"Unhandled exception: {exc}")
                pbar.update(1)

    flush_buffer()
    logger.info(f"Done. Completed: {completed}, Issues: {errors}")
    logger.info(f"Output: {args.output}")


if __name__ == "__main__":
    main()
