import { NAV_ORDER, PAGE_CONFIG } from "./site-config.js";

const SITE_NAME = "ClinReasoningBench Visualizer";

function renderNav(currentKey) {
  return NAV_ORDER.map((key) => {
    const page = PAGE_CONFIG[key];
    const activeClass = key === currentKey ? " is-active" : "";
    return `<a class="site-nav__link${activeClass}" href="${page.path}">${page.navLabel}</a>`;
  }).join("");
}

function applyShell() {
  const pageKey = document.body.dataset.page;
  const page = PAGE_CONFIG[pageKey];
  if (!page) return;

  document.title = page.documentTitle;

  document.querySelectorAll("[data-page-title]").forEach((node) => {
    node.textContent = SITE_NAME;
  });

  document.querySelectorAll("[data-page-heading]").forEach((node) => {
    node.textContent = page.headingTitle;
  });

  document.querySelectorAll("[data-site-nav]").forEach((node) => {
    node.innerHTML = renderNav(pageKey);
  });
}

applyShell();
