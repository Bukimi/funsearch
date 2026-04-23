import ast
import hashlib
import textwrap
import math
from typing import Dict, Any, Tuple, Optional

class ASTNormalizer(ast.NodeTransformer):
    """
    深度 AST 树转换器：抹平变量名差异、清理冗余信息、统一等价的数学与逻辑表达式。
    """
    def __init__(self):
        super().__init__()
        self.name_map = {}
        self.name_counter = 0
        # 扩展白名单：把 Python 内建函数和我们在沙箱中注入的 math 库都加进来
        self.builtins = {
            'range', 'len', 'print', 'list', 'dict', 'set', 
            'int', 'float', 'str', 'bool', 'min', 'max', 'sum',
            'enumerate', 'zip', 'abs', 'True', 'False', 'None',
            'math', 'exp', 'log', 'log10', 'inf'
        }

    def get_normalized_name(self, original_name: str) -> str:
        """为自定义变量生成标准化的名称，例如 var_0, var_1"""
        if original_name in self.builtins:
            return original_name
            
        if original_name not in self.name_map:
            self.name_map[original_name] = f"var_{self.name_counter}"
            self.name_counter += 1
        return self.name_map[original_name]

    def visit_Name(self, node):
        """处理代码中的变量调用"""
        node.id = self.get_normalized_name(node.id)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """统一函数名，并移除无意义的 docstring (注释)"""
        # 1. 移除 docstring
        if ast.get_docstring(node):
            node.body = node.body[1:]
        # 2. 统一函数名为 priority_func，防止 version 序号 (如 priority_v2_v1) 干扰哈希
        node.name = "priority_func"
        return self.generic_visit(node)

    def visit_BinOp(self, node):
        """
        交换律排序 (Commutative Sorting)
        """
        self.generic_visit(node)
        
        if isinstance(node.op, (ast.Add, ast.Mult)):
            try:
                left_str = ast.unparse(node.left)
                right_str = ast.unparse(node.right)
                # 按照字典序强制排序左右节点
                if left_str > right_str:
                    node.left, node.right = node.right, node.left
            except Exception:
                pass 
                
        return node

    def visit_Compare(self, node):
        """
        关系符归一化 (Relational Operator Normalization)
        """
        self.generic_visit(node)
        
        if len(node.ops) == 1 and len(node.comparators) == 1:
            op = node.ops[0]
            left = node.left
            right = node.comparators[0]
            
            if isinstance(op, ast.Gt):
                node.ops[0] = ast.Lt()
                node.left, node.comparators[0] = right, left
            elif isinstance(op, ast.GtE):
                node.ops[0] = ast.LtE()
                node.left, node.comparators[0] = right, left
                
        return node


class CodeDeduplicator:
    """
    多层级代码去重器 (Multi-level Code Deduplicator)
    """
    def __init__(self):
        # 存储 AST 哈希 -> 完整沙箱分数的映射
        self._seen_ast_hashes: Dict[str, Any] = {}
        # 存储语义特征向量 -> 完整沙箱分数的映射
        self._seen_semantic_signatures: Dict[str, Any] = {}
        # 定义微测试集 (item_size, remaining_space)
        self._micro_test_cases = [
            (10.0, 30.0),  
            (50.0, 40.0),  
            (0.1, 0.1),    
            (10.0, 0.0)    
        ]
        # 新增：计数器（两行）
        self.ast_hit_count = 0
        self.semantic_hit_count = 0

    def normalize_code(self, code_str: str) -> str:
        """执行 Level 1: AST 规范化"""
        try:
            clean_code = code_str.replace("```python", "").replace("```", "").strip()
            tree = ast.parse(clean_code)
            
            normalizer = ASTNormalizer()
            normalized_tree = normalizer.visit(tree)
            ast.fix_missing_locations(normalized_tree)
            
            return ast.unparse(normalized_tree)
        except SyntaxError:
            return code_str

    def get_ast_hash(self, code_str: str) -> str:
        """获取 Level 1 的 AST MD5 指纹"""
        norm_code = self.normalize_code(code_str)
        return hashlib.md5(norm_code.encode('utf-8')).hexdigest()

    def get_semantic_signature(self, code_str: str) -> str:
        """
        执行 Level 2: 语义微测试 (Micro-testing)
        """
        signature_values = []
        exec_globals = {
            '__builtins__': {'min': min, 'max': max, 'abs': abs, 'float': float, 'int': int},
            'math': math
        }
        exec_locals = {}
        
        try:
            clean_code = code_str.replace("```python", "").replace("```", "").strip()
            clean_code = textwrap.indent(textwrap.dedent(clean_code), '    ')
            
            exec(clean_code, exec_globals, exec_locals)
            
            func_name = next(n for n in exec_locals.keys() if n.startswith('priority'))
            func = exec_locals[func_name]
            
            for item, space in self._micro_test_cases:
                result = func(item, space)
                signature_values.append(str(round(float(result), 4)))
                
            return "SEMANTIC_[" + "_".join(signature_values) + "]"
            
        except Exception:
            return "ERROR_" + hashlib.md5(code_str.encode('utf-8')).hexdigest()

    def check_duplicate(self, code_str: str) -> Tuple[bool, Optional[Any]]:
        """
        检查代码是否重复，返回 (是否重复, 缓存的分数)
        """
        # 1. Level 1 检查
        ast_hash = self.get_ast_hash(code_str)
        if ast_hash in self._seen_ast_hashes:
            self.ast_hit_count += 1   # 新增
            print(f"[Deduplicator] 🎯 Level-1 命中：AST 结构完全等价！累计 AST 命中: {self.ast_hit_count}")
            return True, self._seen_ast_hashes[ast_hash], 'ast'
            
        # 2. Level 2 检查
        semantic_sig = self.get_semantic_signature(code_str)
        if not semantic_sig.startswith("ERROR_") and semantic_sig in self._seen_semantic_signatures:
            self.semantic_hit_count += 1   # 新增
            print(f"[Deduplicator] 🧠 Level-2 命中：语法不同但语义/功能等价！特征: {semantic_sig}累计语义命中: {self.semantic_hit_count}")
            return True, self._seen_semantic_signatures[semantic_sig], 'semantic'

        return False, None, None

    def register(self, code_str: str, score: Any) -> None:
        """
        将完成沙箱评估的新代码及其分数注册到去重缓存池中
        """
        ast_hash = self.get_ast_hash(code_str)
        self._seen_ast_hashes[ast_hash] = score
        
        semantic_sig = self.get_semantic_signature(code_str)
        if not semantic_sig.startswith("ERROR_"):
            self._seen_semantic_signatures[semantic_sig] = score