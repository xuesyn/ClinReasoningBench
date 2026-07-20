import json
import re
import ast
from typing import Dict, List, Tuple, Optional, Any, Set, Union

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib

# 字体
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
matplotlib.rcParams['axes.unicode_minus'] = False

class graph_tools:
    def __init__(self, graph_path: str = "graph_v1.json"):
        """
        初始化，读取构造图

        输入：字符串，构造图路径，默认为graph_v1.json
        """
        self.graph_path = graph_path

        with open(graph_path, "r", encoding="utf-8") as f:
            self.base_graph = json.load(f)

        # 从json储存元数据
        self.key_meta: Dict[str, Dict[str, Any]] = {}
        for node in self.base_graph.get("nodes", []):
            key = node["key"]
            # 对定义中的 values 列表转小写
            raw_values = node.get("values", [])
            normalized_values = [v.lower() if isinstance(v, str) else v for v in raw_values]
            self.key_meta[key] = {
                "type": node["type"],
                "unit": node.get("unit"),
                "key_id": node.get("key_id"),
                "values": normalized_values,
            }

        # 2. 归一化 rules 里的目标值 (target["value"])
        for rule in self.base_graph.get("rules", []):
            target = rule.get("target", {})
            if "value" in target and isinstance(target["value"], str):
                target["value"] = target["value"].lower()

            # (2) 归一化 expr 中的字符串常量
            # 逻辑：匹配单引号或双引号内的内容，并将其转为小写
            if "expr" in rule and isinstance(rule["expr"], str):
                rule["expr"] = re.sub(
                    r"(['\"])(.*?)\1", 
                    lambda m: m.group(1) + m.group(2).lower() + m.group(1), 
                    rule["expr"]
                )

    @staticmethod
    def parse_tags_from_text(text: str) -> List[Tuple[str, str]]:
        """
        从文本中解析出所有<tag>content</tag>

        输入：str字符串
        返回：列表[(tag_name, content),...]
        """
        pattern = re.compile(r"<([A-Za-z0-9_\-]+)>(.*?)</\1>", re.DOTALL)
        return pattern.findall(text)

    def _convert_value(self, key: str, raw: str) -> Any:
        """
        根据构造图中某个key的type，将文本中的value转转换为对应数据类型

        输入：key，str字符串；raw，content文本，str字符串
        输出：转换结果
        """
        meta = self.key_meta.get(key)
        if meta is None:
            # 未在构造图中定义类型就当成字符串
            return raw.strip()

        t = meta["type"]
        raw_str = raw.strip()

        if t == "int":
            try:
                return int(raw_str)
            except ValueError:
                return raw_str
        if t == "float":
            try:
                return float(raw_str)
            except ValueError:
                return raw_str
        return raw_str.lower()

    def _build_tag_env_from_text(self, text: str) -> Dict[str, Any]:
        """
        从原始文本中parse 所有tag，按json里nodes中定义的类型转换后，得到{key: value}字典，作为环境，即当前文本所存在的所有内容。对于treatment，值为list[str]。其他key取“最后一次出现”的值（等我们检查好gt以后应该不会出现这个问题？）

        输入：str，文本
        输出：dict字典，包含{"key","value"}
        """
        raw_tags = self.parse_tags_from_text(text)
        env: Dict[str, Any] = {}

        for tag_name, content in raw_tags:
            key = tag_name.strip()

            if key not in self.key_meta: # 只有定义过的key才保存，没定义过的不管
                continue

            if key == "treatment":
                if "treatment" not in env:
                    env["treatment"] = []

                value = self._convert_value(key, content)
                if value not in env["treatment"]:
                    env["treatment"].append(value)
                    
            else:
                env[key] = self._convert_value(key, content)

        return env
    
    # 表达式求值，并且求带“贡献了表达式的值为真”的key的集合
    def _normalize_expr(self, expr: str) -> str:
        """
        将规则里的expr转换成python格式，'&&'->'and'，'||'->'or'

        输入：str，表达式
        输出：str，转换后的表达式
        """
        s = expr
        s = s.replace("&&", " and ")
        s = s.replace("||", " or ")
        s = re.sub(r'!\s*(?=[A-Za-z_(])', ' not ', s)

        return s
    
    def calculate_expr(
        self, expr: str, tag_env: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        传入规则表达式和当前文本中可用的tag的值，如果表达式中的变量文本中有缺失，and逻辑默认true，or逻辑默认false，
        
        输入：文本表达式，当前文本tag-content
        返回：元组，第一个bool值表示整个表达式是否为真，第二个列表“支持该表达式为真”的 key 列表
        递归的底层语境默认按and处理
        """
        if not expr:
            return True, []

        expr_python = self._normalize_expr(expr) # 写json的时候写成C的语法了，换成python的

        try:
            tree = ast.parse(expr_python, mode="eval")
        except SyntaxError:
            # 如果表达式有语法问题，当True处理，到时候应该可以不管
            return True, []

        val, support_keys, _known = self._eval_ast_with_support(
            tree.body,
            tag_env,
            context_logic="and",
        )
        return val, sorted(support_keys)

    
    def _eval_simple(self, node: ast.AST, env: Dict[str, Any]) -> Any:
        """
        基本逻辑运算
        """
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self._eval_simple(elt, env) for elt in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_simple(elt, env) for elt in node.elts)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = self._eval_simple(node.operand, env)
            try:
                return -val
            except Exception:
                return val
        code = compile(ast.Expression(node), "<expr>", "eval")
        return eval(code, {}, env)


    def _eval_ast_with_support(
        self,
        node: ast.AST,
        env: Dict[str, Any],
        context_logic: str = "and",  # 表示当前子表达式在递归的父级是以什么逻辑连接
    ) -> Tuple[bool, Set[str], bool]:

        """
        在给定env和逻辑上下文（当前参与and还是or运算）下递归求值
        
        返回：元组第一个bool为表达式布尔值，第二个集合为“支持该式为真”的 key 集合

        具体解释
        当基本逻辑运算出现缺失变量时，缺失该变量的整个逻辑表达式如下处理：
            若在 AND 语境：视为True，support=空集合
            若在 OR 语境：视为False，support=空集合
        这样整个规则可以用来做 GT 检查，只有出现“显式冲突，明显矛盾”的tag才会把表达式变False。

        AND:
            所有子式均为True -> True，support=所有子式support的并集
            一旦某子式为False->False，support=空集合
        OR:
            先收集所有 True 子式的support：若所有True子式support都为空->整体True, support为空
            否则看非空support：若存在一个 support S 是所有其他 support 的真子集且唯一，则选这个 S（“最小解释”），即支持该式子为真的key集合；否则，将所有非空 support求并集（对称条件一起贡献）。
        """
        def _neutral(parent_logic: str) -> bool:
            # 作为父运算的中性元：AND->True, OR->False
            return True if parent_logic == "and" else False

        if isinstance(node, ast.BoolOp):
            # ===== AND =====
            if isinstance(node.op, ast.And):
                child_context = "and"  # 子条件缺失时按 AND 中性元处理
                overall_support: Set[str] = set()
                any_known = False

                for value in node.values:
                    v, s, known = self._eval_ast_with_support(value, env, context_logic=child_context)
                    if known:
                        any_known = True
                        if not v:
                            # 明确矛盾：AND 中出现已知 False
                            return False, set(), True
                        overall_support |= s
                    # known=False 的子式（纯缺失）不影响 AND（相当于 True）

                if not any_known:
                    # 整个括号完全由缺失组成 => 作为父运算的中性元
                    return _neutral(context_logic), set(), False

                return True, overall_support, True

            # ===== OR =====
            if isinstance(node.op, ast.Or):
                child_context = "or"   # 子条件缺失时按 OR 中性元处理
                any_known = False
                known_true_supports: List[Set[str]] = []
                saw_known_true = False
                saw_known_false = False

                for value in node.values:
                    v, s, known = self._eval_ast_with_support(value, env, context_logic=child_context)
                    if known:
                        any_known = True
                        if v:
                            saw_known_true = True
                            known_true_supports.append(s)
                        else:
                            saw_known_false = True
                    # known=False 的子式（纯缺失）不影响 OR（相当于 False）

                if not any_known:
                    # 整个括号完全由缺失组成 => 作为父运算的中性元
                    return _neutral(context_logic), set(), False

                if saw_known_true:
                    # OR 为真：沿用你原来的“最小解释/并集”策略（只对 known True 的子式）
                    nonempty_supports = [s for s in known_true_supports if len(s) > 0]
                    if not nonempty_supports:
                        return True, set(), True

                    minimal_sets: List[Set[str]] = []
                    for s in nonempty_supports:
                        ok = True
                        for t in nonempty_supports:
                            if s is t:
                                continue
                            if not (s < t):
                                ok = False
                                break
                        if ok:
                            minimal_sets.append(s)

                    if len(minimal_sets) == 1:
                        return True, minimal_sets[0].copy(), True

                    union_support: Set[str] = set()
                    for s in nonempty_supports:
                        union_support |= s
                    return True, union_support, True

                # 没有 known True，但有 known（说明 known 全是 False）=> OR 明确为 False
                return False, set(), True


        # 一元运算
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            # not不改变语境，直接把当前context_logic传下去
            v, s, known = self._eval_ast_with_support(node.operand, env, context_logic=context_logic)
            return (not v), s, known


        # 比较表达式
        if isinstance(node, ast.Compare):
            # 收集此比较中所有变量名
            names: Set[str] = set()

            def collect_names(n: ast.AST):
                if isinstance(n, ast.Name):
                    names.add(n.id)
                for child in ast.iter_child_nodes(n):
                    collect_names(child)

            collect_names(node.left)
            for comp in node.comparators:
                collect_names(comp)

            missing = [n for n in names if n not in env]
            if missing:
                # 这个比较式完全没有可用信息（至少缺一个变量）=> unknown
                # 返回“在本层运算中的中性值”，并标记 known=False
                if context_logic == "and":
                    return True, set(), False
                else:
                    return False, set(), False

            left_val = self._eval_simple(node.left, env)
            result = True
            cur_left = left_val
            for op, comparator in zip(node.ops, node.comparators):
                right_val = self._eval_simple(comparator, env)
                if isinstance(op, ast.In):
                    ok = cur_left in right_val
                elif isinstance(op, ast.NotIn):
                    ok = cur_left not in right_val
                elif isinstance(op, ast.Eq):
                    ok = cur_left == right_val
                elif isinstance(op, ast.NotEq):
                    ok = cur_left != right_val
                elif isinstance(op, ast.Lt):
                    ok = cur_left < right_val
                elif isinstance(op, ast.LtE):
                    ok = cur_left <= right_val
                elif isinstance(op, ast.Gt):
                    ok = cur_left > right_val
                elif isinstance(op, ast.GtE):
                    ok = cur_left >= right_val
                else:
                    ok = True  # 表达式有问题设为true

                if not ok:
                    result = False
                    break
                cur_left = right_val  # 链式比较

            if result:
                # 比较为真，贡献所有涉及的变量名
                return True, names,True
            else:
                return False, set(),True

        if isinstance(node, ast.Name):
            if node.id in env:
                return bool(env.get(node.id)), {node.id}, True
            # 缺失：作为当前逻辑运算的中性元，且 known=False
            if context_logic == "and":
                return True, set(), False
            else:
                return False, set(), False


        if isinstance(node, ast.Constant):
            return bool(node.value), set(), True

        return bool(self._eval_simple(node, env)), set(),True

    def validate_tag_env(self, tag_env: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        校验 tag_env 是否满足：
        1) 数值类型（int/float）符合 nodes 中定义的 type
        2) 离散取值（values 非空）必须落在定义范围内
        返回：
            has_error, errors
        """
        errors: List[Dict[str, Any]] = []

        # ===== 1) 类型鲁棒性检查 =====
        for key, val in tag_env.items():
            meta = self.key_meta.get(key)
            if not meta:
                continue

            expected_type = meta.get("type")

            # treatment 不做数值类型校验
            if key == "treatment":
                continue

            if expected_type == "int":
                # bool 是 int 子类，一般不希望当 int
                if (not isinstance(val, int)) or isinstance(val, bool):
                    errors.append({
                        "id": None,
                        "kind": "type_error",
                        "target": {"key": key, "value": val},
                        "error": "数值类型错误",
                        "describe": f"请检查<{key}>的数值类型",
                    })

            elif expected_type == "float":
                # 允许 int 也算 float（比如 5），但不允许 str
                if (not isinstance(val, (int, float))) or isinstance(val, bool):
                    errors.append({
                        "id": None,
                        "kind": "type_error",
                        "target": {"key": key, "value": val},
                        "error": "数值类型错误",
                        "describe": f"请检查<{key}>的数值类型",
                    })

        # 若类型已错，后面 values 校验也可以继续做（一起报），也可以直接 return
        # 这里选择：继续做 values，一次性给全量错误

        # ===== 2) 离散取值合法性检查（values）=====
        for key, val in tag_env.items():
            meta = self.key_meta.get(key)
            if not meta:
                continue

            allowed_values = meta.get("values", [])
            if not allowed_values:
                continue  # 没定义 values 就不校验

            if key == "treatment":
                # treatment 应该是 list
                if isinstance(val, list):
                    invalid = [v for v in val if v.lower() not in [allowed_value.lower() for allowed_value in allowed_values]]
                    if invalid:
                        errors.append({
                            "id": None,
                            "kind": "value_error",
                            "target": {"key": key, "value": val},
                            "error": "离散取值错误",
                            "describe": f"请检查<{key}>的取值是否在定义范围内",
                            "invalid_values": invalid,
                        })
                else:
                    # 防御分支
                    if val not in allowed_values:
                        errors.append({
                            "id": None,
                            "kind": "value_error",
                            "target": {"key": key, "value": val},
                            "error": "离散取值错误",
                            "describe": f"请检查<{key}>的取值是否在定义范围内",
                            "invalid_values": [val],
                        })
            else:
                # 标量
                if val not in allowed_values:
                    errors.append({
                        "id": None,
                        "kind": "value_error",
                        "target": {"key": key, "value": val},
                        "error": "离散取值错误",
                        "describe": f"请检查<{key}>的取值是否在定义范围内",
                        "invalid_values": [val],
                    })

        return (len(errors) > 0), errors

    # 构造子图
    def build_subgraph(
        self,
        text: Optional[str] = None,
        text_path: Optional[str] = None,
        save_json_path: Optional[str] = None,
        save_img_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从文本或文本文件中提取<tag>，构造对应的子图。
        输入：从text/text_path二选一
        返回字典:
          {
            "nodes": [...],
            "routes": [...]
          }
        """
        if (text is None and text_path is None) or (
            text is not None and text_path is not None
        ):
            raise ValueError("text 与 text_path 必须二选一。")

        if text is None:
            with open(text_path, "r", encoding="utf-8") as f:
                text = f.read()

        # 1. 从文本中解析tag，构造当前GT的key-value
        tag_env = self._build_tag_env_from_text(text)

        # 2. 构造子图nodes：只包含出现在tag_env中的key
        sub_nodes: List[Dict[str, Any]] = []
        for key, val in tag_env.items():
            meta = self.key_meta.get(key)
            if not meta:
                continue
            node_entry = {
                "key": key,
                "type": meta["type"],
                "key_id": meta["key_id"],
                "value": val,
            }
            sub_nodes.append(node_entry)

        has_env_error, env_errors = self.validate_tag_env(tag_env)
        if has_env_error:
            routes: List[Dict[str, int]] = []
            subgraph = {
                "nodes": sub_nodes,
                "routes": routes,
                # 如果你愿意，也可以把错误挂在 subgraph 里，便于调试/可视化
                # "errors": env_errors,
            }

            if save_json_path is not None:
                with open(save_json_path, "w", encoding="utf-8") as f:
                    json.dump(subgraph, f, ensure_ascii=False, indent=2)

            if save_img_path is not None:
                self.draw_graph(subgraph, save_img_path)

            return subgraph
        
        # 3. 遍历所有rules，生成route
        routes: List[Dict[str, int]] = []
        route_set: Set[Tuple[int, int]] = set()
        rules = self.base_graph.get("rules", [])

        for rule in rules:
            target = rule.get("target", {})
            target_key = target.get("key")
            target_val = target.get("value")

            if not target_key or target_key not in tag_env:
                continue

            # target的value须匹配GT中的值
            if target_key == "treatment":
                tx_list = tag_env.get("treatment", [])
                if target_val not in tx_list:
                    continue
            else:
                if tag_env.get(target_key) != target_val:
                    continue

            # required_keys与当前出现的tag是否有交集
            required_keys: List[str] = rule.get("required_keys", [])
            present_keys = set(tag_env.keys())
            if not (present_keys & set(required_keys)):
                continue

            # 计算表达式，并找出支持该式为真的key
            expr = rule.get("expr", "")
            expr_val, support_keys = self.calculate_expr(expr, tag_env)

            if not expr_val:
                # 这条规则在当前标签下并不成立，不生成边
                continue

            # 为每一个“支持该式为真”的 key，构造边support_key -> target_key
            target_meta = self.key_meta.get(target_key)
            if not target_meta:
                continue
            to_id = target_meta["key_id"]

            for k in support_keys:
                meta_k = self.key_meta.get(k)
                if not meta_k:
                    continue
                from_id = meta_k["key_id"]
                edge = (from_id, to_id)
                if edge not in route_set:
                    route_set.add(edge)
                    routes.append(
                        {
                            "from": from_id,
                            "to": to_id,
                        }
                    )

        # 4. 给routes加route_id
        for idx, r in enumerate(routes, start=1):
            r["route_id"] = idx

        subgraph = {
            "nodes": sub_nodes,
            "routes": routes,
        }

        # 5. 保存为 JSON
        if save_json_path is not None:
            with open(save_json_path, "w", encoding="utf-8") as f:
                json.dump(subgraph, f, ensure_ascii=False, indent=2)

        # 6. 保存 PNG
        if save_img_path is not None:
            self.draw_graph(subgraph, save_img_path)

        return subgraph
    
    def check_gt(
        self,
        text: Optional[str] = None,
        text_path: Optional[str] = None,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        检查一段GT文本是否存在规则矛盾或不匹配。

        逻辑：
        - 遍历所有 rules：
        - staging_rule:
            若文本中给出了 <staging>，且其值与 target.value 相同，且 rule.required_keys 与已出现 tag 有交集，但 rule.expr 在当前 tag_env 下为 false，则判定为“分期矛盾”。
        - treatment_requirement:
            若文本中出现了某个 <treatment>，且与 target.value 相同，且 rule.required_keys 与已出现 tag 有交集，但 rule.expr 为 False，则判定为“治疗必要条件不满足”（禁忌）。
        - treatment_recommend:
            若文本中出现了某个 <treatment>，且与 target.value 相同，且 rule.required_keys 与已出现 tag 有交集，但 rule.expr 为 False，则判定为“治疗推荐与分期不匹配”。
            上面三个逻辑在程序上是等价的，我只是分别说明了
        - 对于完全没有涉及这条rule的任何required_keys的GT，不检查该rule。
        """

        if (text is None and text_path is None) or (
            text is not None and text_path is not None
        ):
            raise ValueError("text 与 text_path 必须二选一。")

        # 读取文本
        if text is None:
            with open(text_path, "r", encoding="utf-8") as f:
                text = f.read()

        # 1. 解析文本中的 tag，当前env
        tag_env = self._build_tag_env_from_text(text)
        present_keys = set(tag_env.keys())

        # ===== 新增：先做类型/values 校验，失败直接返回 =====
        has_env_error, env_errors = self.validate_tag_env(tag_env)
        if has_env_error:
            return True, env_errors
        # ===== 新增结束 =====

        violated: List[Dict[str, Any]] = []

        # 2. 遍历所有规则
        for rule in self.base_graph.get("rules", []):
            kind = rule.get("kind")

            # if kind not in ("staging_rule", "treatment_requirement", "treatment_recommend"):
            #     continue

            target = rule.get("target", {})
            target_key = target.get("key")
            target_val = target.get("value")

            if not target_key:
                continue

            # required_keys必须和当前GT中出现的tag有交集，否则跳过
            rule_required = rule.get("required_keys", [])
            if rule_required:
                if present_keys.isdisjoint(rule_required):
                    continue

            # 这条规则是否包含对应的value
            if target_key == "treatment":
                treatments = tag_env.get("treatment", [])
                if target_val not in treatments:
                    # 文本中没有选择这个治疗则不检查这条规则
                    continue
            elif target_key == "staging":
                if tag_env.get("staging") != target_val:
                    continue # 不是这个分期则不检查这条规则
            else:
                if tag_env.get(target_key) != target_val:
                    continue

            # 目标匹配，如果至少有一个required_key出现在文本中，说明这条rule在当前GT中被使用，检查expr。
            expr = rule.get("expr", "")
            expr_val, _ = self.calculate_expr(expr, tag_env)

            if not expr_val:
                # 出现矛盾，记录 id、描述、类型
                violated.append(
                    {
                        "id": rule.get("id"),
                        "kind": kind,
                        "target": target,
                        "required_keys": rule_required,
                        "describe": rule.get("describe", ""),
                    }
                )

        has_conflict = len(violated) > 0
        return has_conflict, violated
    
    @staticmethod
    def get_descendants(
        graph_input: Optional[Union[Dict, str]] = None,
        graph_input_path: Optional[str] = None,
        key: Optional[str] = None,
        key_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        函数， 给一个子图都可以 + key或者key_id，返回该节点的所有“子孙节点”，不包含起点本身，如果没有后继结点则返回空列表

        输入：
            graph_input:可以是字典（已经jsonload过的 graph）也可以是字符串。如果是 JSON 文本：用 json.loads 解析
            graph_input_path:文件路径,尝试 open 然后json.load
                路径和内容二选一传入。如果都没传入默认用类中的graph。
            key:     节点的 key 名（如 "staging"）
            key_id:  节点的 key_id（如 28）
            key 和 key_id 二选一，不能都空，也不能都填。

        返回：
            子孙节点列表（节点 dict 列表）
        """
        # 参数校验
        if graph_input is not None and graph_input_path is not None:
            raise ValueError("路径和内容不可以都传")
        elif graph_input is None and graph_input_path is None:
            raise ValueError("需要传入路径或内容")
        if (key is None and key_id is None) or (key is not None and key_id is not None):
            raise ValueError("须传入key或key_id中任意一个")
        
        if graph_input_path is not None:
            # 从文件路径读取
            with open(graph_input_path, "r", encoding="utf-8") as f:
                graph = json.load(f)
        elif graph_input is not None:
            # 使用传进来的内容
            if isinstance(graph_input, dict):
                graph = graph_input
            elif isinstance(graph_input, str):
                graph = json.loads(graph_input)
            else:
                raise TypeError("graph_input必须是字典或字符串")

        nodes = graph.get("nodes", [])
        routes = graph.get("routes", [])

        # 邻接表：from_id -> [to_id, ...]
        adj: Dict[int, List[int]] = {}
        for r in routes:
            f = r.get("from")
            t = r.get("to")
            if f is None or t is None:
                continue
            adj.setdefault(f, []).append(t)

        # 找起始节点的key_id集合
        if key is not None:
            start_ids = {n["key_id"] for n in nodes if n.get("key") == key}
        else:  # 用key_id
            start_ids = {n["key_id"] for n in nodes if n.get("key_id") == key_id}

        if not start_ids:
            return []

        # BFS方法寻找所有后代节点
        visited = set(start_ids)
        descendants = set()
        queue = list(start_ids)

        while queue:
            cur = queue.pop(0)
            for nxt in adj.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    descendants.add(nxt)
                    queue.append(nxt)

        # 按原 nodes 顺序返回这些后代节点
        result = [n for n in nodes if n["key_id"] in descendants]
        return result
    
    # ========= 画子图：networkx + matplotlib =========
    # ChatGPT生成，没检查，能用就行，就是看看
    @staticmethod
    def draw_graph(subgraph: Dict[str, Any], output_path: str):
        """
        绘制子图，保存为 PNG。
        节点标签：key\\n(value)
        """
        G = nx.DiGraph()

        # 加节点
        for node in subgraph["nodes"]:
            key_id = node["key_id"]
            key = node.get("key", "")
            value = node.get("value", "")
            # list 的情况（如 treatment 多个）转成逗号拼接的字符串
            if isinstance(value, list):
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = str(value)
            label = f"{key}\n({value_str})"
            G.add_node(key_id, label=label)

        # 加边
        for route in subgraph["routes"]:
            G.add_edge(route["from"], route["to"])

        if len(G) == 0:
            print("子图为空，无法绘制。")
            return

        pos = nx.spring_layout(G, seed=23, k=0.8)  # k 越大，节点越“松散”

        plt.figure(figsize=(12, 8))

        # 节点
        nx.draw_networkx_nodes(G, pos, node_size=1200)

        # 边：有弧度、带箭头，避免被圆盖住
        nx.draw_networkx_edges(
            G,
            pos,
            edgelist=G.edges(),
            arrows=True,
            arrowstyle='-|>',
            arrowsize=20,
            width=2,
            connectionstyle='arc3,rad=0.2',
            min_source_margin=15,
            min_target_margin=15,
        )

        # 标签
        labels = nx.get_node_attributes(G, "label")
        nx.draw_networkx_labels(G, pos, labels=labels, font_size=8)

        plt.axis("off")
        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        plt.close()
        print(f"子图已保存为 {output_path}")

if __name__ == "__main__": 
    gt = graph_tools(graph_path="cnlc_graph_beta_v1.json")

    text = """
患者为18岁男性，确诊为肝细胞癌（Hepatocellular carcinoma, NOS），中分化，组织学类型为梁状型。病灶位于肝右叶，肿瘤大小为<num_tumor>1</num_tumor>肿瘤，最大肿瘤直径为<max_tumor_size>8.0</max_tumor_size>cm，影像学提示肝右叶存在单发占位性病变，伴有“快进快出”特征；肝周显著纤维化<fibrosis>有</fibrosis>，门静脉未见充盈缺损<macrovascular_invasion>无</macrovascular_invasion>，<cancer_thrombus>无</cancer_thrombus>癌栓。无临近组织侵犯、无淋巴结转移证据，亦未见远处转移<metastasis>无</metastasis>或肺、骨等常见远处转移部位的异常表现。患者一般状态良好，PS评分为<ps>1</ps>。肝功能<child_pugh>A</child_pugh>级，肝脏储备检测的R15值为<ICG_R15>6.0</ICG_R15>%。实验室检查结果无明显异常，未发现乙肝标志物阳性（HBsAg阴性，HBcAg阴性），且AFP水平正常。\n\n# 判断分期 根据CNLC分期系统：1. 患者<ps>1</ps>、<child_pugh>A</child_pugh>级，满足第一步基础条件筛查。影像学未提示血管侵犯<macrovascular_invasion>无</macrovascular_invasion>，未见肝外转移<metastasis>无</metastasis>。肿瘤数量为<num_tumor>1</num_tumor>，肿瘤最大直径为<max_tumor_size>8.0</max_tumor_size>厘米，明显大于5厘米，符合CNLC <staging>I_b</staging>期标准。\n\n# 根据CNLC决策树进行初步决策 根据决策树，CNLC Ib期推荐的治疗选项包括：手术切除、TACE、消融、TACE+消融，以及可能的肝移植。\n\n# 对于每个潜在方案的细节分析 \n1. 手术切除：根据指南，CNLC Ib期的患者若肝脏储备功能足够，应首选<child_pugh>A</child_pugh>，无肝外转移<metastasis>无</metastasis>，<ICG_R15>6.0</ICG_R15>%，远远低于10%这一进行大范围肝切除的安全标准。，此外，患者无其他手术禁忌证，因此完全可以实施<treatment>手术切除</treatment>。\n  - 是否满足指征：满足，符合手术切除的指征。\n  - 是否违反禁忌证：未违反禁忌证。\n  - 缺失信息：无缺失信息。\n\n2. TACE：根据指南，TACE适应症适用于无法进行根治性手术或消融的Ib期患者，以及不可切除肿瘤的桥接治疗等情形。患者目前适合<metastasis>无</metastasis>手术切除，并不属于需要首选<child_pugh>A</child_pugh>TACE的对象。但对于后期辅助治疗或联合治疗可以讨论。\n  - 是否满足指征：较低满足，仅限无法手术条件下使用。\n  - 是否违反禁忌证：未见明显禁忌，但非优选治疗。\n  - 缺失信息：无缺失信息。\n\n3. 消融治疗：消融适用于5厘米以下单发肿瘤和部分2-3个病灶最大直径均小于3厘米的病例。患者肿瘤最大直径为<max_tumor_size>8.0</max_tumor_size>厘米，超过消融治疗的理想适应证范围。若结合TACE，可在一定情况下考虑作为联合治疗，但单独应用<child_pugh>A</child_pugh>消融有限制。\n  - 是否满足指征：不满足。\n  - 是否违反禁忌证：无禁忌证，但不符合指征。\n  - 缺失信息：无。\n\n4. TACE+消融：据CNLC指南联合治疗对3-7厘米直径病灶有更高疗效。虽然患者肿瘤直径为8厘米，略超适应证范围，但在MDT评估后可适当探讨。\n  - 是否满足指征：部分满足。\n  - 是否违反禁忌证：未违反禁忌证。\n  - 缺失信息：需进一步明确病灶解剖特征。\n\n5. 肝移植：肝移植更适用于肝功能失代偿或无法进行根治手术与消融的小肝癌。患者目前肝功能良好<child_pugh>A</child_pugh>，肿瘤适合手术切除，且移植需要优先考虑资源配置的公平性，因此目前<treatment_not_recommended>肝移植</treatment_not_recommended>。\n  - 是否满足指征：不满足条件。\n  - 是否违反禁忌证：不违反禁忌。\n  - 缺失信息：无。\n\n# 综合分析 患者属于CNLC <staging>I_b</staging>期，其最佳治疗推荐为<treatment>手术切除</treatment>。虽然TACE和消融治疗也可考虑，但均非本例的首选，且消融因不满足肿瘤大小要求而具有局限性。肝移植保留供肝资源，应优先用于更有需要的患者。因此可以得出最终推荐排序：<treatment>手术切除</treatment> > <treatment>TACE + 消融</treatment> > <treatment>TACE</treatment> > <treatment_not_recommended>消融治疗</treatment_not_recommended> > <treatment_not_recommended>肝移植</treatment_not_recommended>。


    """

    has_conflict, violated = gt.check_gt(text=text)
    # 输入文本字符串或者文本路径
    # 返回一个元组，第一个元素为bool，标识有无错误。第二个元素为列表，列表内为字典，键有下面print里面的几个
    print("有无不匹配:", has_conflict)
    for r in violated:
        print(r["id"], r["kind"], r["target"], r["describe"])

    subgraph = gt.build_subgraph(text=text,save_img_path="subgraph.png",save_json_path="subgraph.json")
    # 输入文本字符串或者文本路径，可以选择输出子图json和png路径
    # 返回一个字典，格式和json那个一样
    print(subgraph)

    subnodes=gt.get_descendants(graph_input=subgraph,key="ps")
    # 生成所有子孙节点
    #print(subnodes)