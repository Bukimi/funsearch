import multiprocessing
import time
import traceback
import math
from typing import Dict, Any, Tuple, List, Callable

# =========================================================================
# 【核心评测逻辑】在线装箱模拟器
# 此部分在隔离的子进程中运行，用于计算代码的 Fitness。
# 我们追求：箱子数量越少，分数越高 -> 使用 -(箱子数量) 作为 Fitness。
# =========================================================================

def _fit_bin_packing_simulator(items: List[float], capacity: float, priority_function: Callable) -> float:
    """
    使用 LLM 生成的优先级函数模拟在线 First-Fit-Strategy (或变体) 装箱过程。
    
    策略：对于每个物品，评估所有已打开的箱子和新箱子，将其放入优先级最高的合法箱子中。
    """
    # 记录每个已打开箱子的剩余空间
    open_bins: List[float] = [] 
    
    for item in items:
        # 如果物品本身比箱子容量还大，这在物理上是非法的
        if item > capacity:
            return -float('inf') 
            
        best_existing_bin_index = -1
        max_existing_priority = -float('inf')
        
        # 1. 评估已打开的箱子
        for i, remaining_space in enumerate(open_bins):
            # 只有当物品放得进去时才考虑
            if item <= remaining_space:
                try:
                    # 调用 LLM 生成的算法计算优先级
                    # 输入：物品大小，箱子剩余空间
                    priority = priority_function(item, remaining_space)
                    if priority > max_existing_priority:
                        max_existing_priority = priority
                        best_existing_bin_index = i
                except Exception:
                    # 如果生成的代码运行出错（例如除以 0），直接导致该样本评估失败
                    raise

        # 2. 评估一个潜在的新箱子
        # 认为新箱子的剩余空间等于其额定容量
        try:
            new_bin_priority = priority_function(item, capacity)
        except Exception:
            raise

        # 3. 决策逻辑 (Best-Fit-like based on priority)
        # 比较：是在已有箱子中找最佳的，还是新开一个箱子更好
        if best_existing_bin_index != -1 and max_existing_priority >= new_bin_priority:
            # 放入优先级最高的已有箱子
            open_bins[best_existing_bin_index] -= item
        else:
            # 新开一个箱子并放入物品
            open_bins.append(capacity - item)
            
    # 计算箱子数量 (越低越好)
    num_bins = len(open_bins)
    
    # 返回适应度分数 (越高越好)。最小化 num_bins 等同于最大化 -num_bins
    return float(-num_bins)


# =========================================================================
# 【工人进程逻辑】负责在受限环境下安全地 `exec` 代码
# =========================================================================

def _worker_process(
    source_code: str,
    target_heuristic_name: str,
    instance_items: List[float],
    bin_capacity: float,
    result_queue: multiprocessing.Queue
    
):
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ['math', 'collections', 'itertools']:
            return __import__(name, globals, locals, fromlist, level)
        raise ImportError(f"Sandbox Security: 禁止导入危险模块 '{name}'")

    """
    在隔离环境中执行原始代码字符串，运行 simulator，并返回分数。
    """
    # 1. 设置极其受限的内置全局变量，防止恶意代码调用 os, sys, exec, eval 等
    safe_builtins = {
        'abs': abs, 'all': all, 'any': any, 'bool': bool, 'divmod': divmod,
        'enumerate': enumerate, 'float': float, 'int': int, 'len': len,
        'list': list, 'max': max, 'min': min, 'pow': pow, 'range': range,
        'round': round, 'set': set, 'str': str, 'sum': sum, 'tuple': tuple,
        'zip': zip, 'ZeroDivisionError': ZeroDivisionError,
        'Exception': Exception, 'NameError': NameError, 'ValueError': ValueError,
        'TypeError': TypeError, 'print': print,
        '__import__': safe_import  # <--- 【核心修改】：注入安全 import
    }
    
    exec_globals = {
        '__builtins__': safe_builtins,
        'math': math,
    }
    # 用于捕获生成的函数定义
    exec_locals = {}
    
    try:
        # 2. 执行 LLM 生成的代码
        # 此时整个 Skeleton (priority_v1 和新的 priority_v2) 会被注册到局部空间
        # 【新增】：把即将执行的最终拼装代码打印出来，抓出缩进真凶！
        print("\n=== [Sandbox Debug] 即将放入 exec 执行的完整拼装代码 ===")
        #print(source_code)
        print("========================================================\n")
        exec(source_code, exec_globals, exec_locals)
        
        # 3. 提取目标启发式函数
        if target_heuristic_name not in exec_locals:
            raise NameError(f"未能在生成的代码中找到指定的入口函数 '{target_heuristic_name}'")
        
        # 获取实际运行的优先级函数句柄
        generated_priority_func = None
        # 优先寻找带 _v 后缀的最新生成函数 (例如 priority_v2_v0)
        for name, func in exec_locals.items():
            if name.startswith(target_heuristic_name) and callable(func) and name != target_heuristic_name:
                generated_priority_func = func
                break
                
        # 如果没找到带后缀的，再尝试获取原名
        if generated_priority_func is None and target_heuristic_name in exec_locals:
            generated_priority_func = exec_locals[target_heuristic_name]
            
        if generated_priority_func is None:
            raise NameError(f"沙箱未能在代码中找到 '{target_heuristic_name}' 或其变种函数。")
        
        # 4. 运行真实的装箱模拟器进行打分
        fitness_score = _fit_bin_packing_simulator(instance_items, bin_capacity, generated_priority_func)
        # 5. 将得分通过队列返回给主进程
        result_queue.put({"status": "success", "score": fitness_score})
        
    except Exception as e:
        # 捕获运行时错误（如 division by zero），并返回错误摘要和 traceback
        error_details = traceback.format_exc()
        error_summary = f"{type(e).__name__}: {str(e)}"
        result_queue.put({"status": "error", "message": error_summary, "details": error_details})


# =========================================================================
# 【主沙箱类】供 evaluator.py 调用
# =========================================================================

class Sandbox:
    """
    多进程安全的沙箱评估器。
    无缝对接 funsearch/implementation/evaluator.py。
    """
    def __init__(self, bin_capacity: float = 100.0, target_heuristic_name: str = "priority_v2"):
        """
        Args:
            bin_capacity: OR 数据集中定义的箱子标准容量。
            target_heuristic_name: LLM 生成代码中负责计算优先级的函数名。
                                   它确定了模拟器在 simulation 过程中该调用谁。
        """
        self.bin_capacity = bin_capacity
        # 根据我们之前的 Prompt 规划，这里默认为 'priority_v2'
        self.target_heuristic_name = target_heuristic_name
            
    def run(
        self,
        program: Any, # 这里是 evaluator.py 传入的内部 Program 对象
        function_to_run: str, # 官方 evaluator.py 这里传的是用来包裹执行的虚拟入口名，在我们的简化版沙箱中主要用于日志，直接由 simulator 执行
        current_input: Any,   # 这里的输入必须是 List[float] (物品大小列表)
        timeout_seconds: int
    ) -> Tuple[float | None, bool]:
        """
        运行给定的程序 AST 对象来评估其适应度分数。
        
        此方法接口签名严格符合 evaluator.py 对沙箱的预期。
        """
        # Security: 严格检查输入数据类型。Bin Packing 的 current_input 必须是物品大小列表
        if not isinstance(current_input, list):
            print(f"[Sandbox Error]current_input 格式错误。预期 List[float] (物品列表)。")
            return None, False

        # 1. 将 FunSearch 内部的 Program 对象转换为可供 exec() 的 Python 代码字符串
        # 依赖 code_manipulation.py 的实现，通常 str(program) 可行。
        try:
            source_code_str = str(program)
        except Exception as e:
            print(f"💥 [Sandbox Error] 致命错误：无法将 Program AST 转换为字符串: {e}")
            return None, False

        # 建立 IPC 队列
        result_queue = multiprocessing.Queue()
        # 建立并启动执行子进程
        process = multiprocessing.Process(
            target=_worker_process,
            args=(source_code_str, self.target_heuristic_name, current_input, self.bin_capacity, result_queue)
        )
        
        # 计时开始
        process.start()
        
        # 等待指定的超时时间
        process.join(timeout=float(timeout_seconds))
        
        # 2. 检查子进程是否仍在存活 (即：是否发生了死循环导致的超时)
        if process.is_alive():
            process.terminate() # 强制终止进程
            process.join() # 确保资源被回收
            print(f"[Sandbox Timeout] 装箱模拟超时，已强制终止。超时设定为 {timeout_seconds}秒。")
            return None, False # 返回失败，分数为空
                
        # 3. 检查队列是否为空 (可能发生了严重的内存溢出或进程崩溃)
        if result_queue.empty():
            print(f"[Sandbox SystemError] 模拟器进程异常退出，未返回结果（可能发生了内存泄漏被系统 kill 或 Segmentation fault）。")
            return None, False # 返回失败，分数为空
                
        # 4. 正常运行结束，处理队列中的结果
        result = result_queue.get()
        
        if result["status"] == "success":
            # 评估成功，返回适应度分数 (即 -(所用箱子数量))
            return result["score"], True
        else:
            # 评估失败（代码抛出异常，如 Division by Zero）
            # 对于你的实验，你可以在这里记录或打印具体错误 result['message'] 和 result['details']
            # print(f"[Sandbox GenCode Runtime Error] 生成的代码中抛出了运行时异常: {result['message']}")
            print(f"💥 [Sandbox Error] 沙箱执行失败！")
            print(f"    -> 错误摘要: {result['message']}")
            print(f"    -> 详细追踪:\n{result['details']}")
            return None, False

# =========================================================================
# 【本地单元测试块】可以直接运行此文件测试沙箱功能是否正常
# =========================================================================
if __name__ == "__main__":
    import multiprocessing
    # Windows/Mac 需要以此兼容性代码启动多进程
    multiprocessing.freeze_support()
    
    print("=== 开始运行 Sandbox.py 独立单元测试 ===\n")
    
    # 模拟项目中的 Program 对象
    class MockProgram:
        def __init__(self, code): self.code = code
        def __str__(self): return self.code

    # 初始化针对装箱问题的沙箱 (容量 100，优化 priority_v2)
    sandbox_instance = Sandbox(bin_capacity=100.0, target_heuristic_name="priority_v2")
    
    # 测试数据 instance (10个物品)
    test_instance = [10.5, 30.0, 90.0, 50.5, 60.0, 20.0, 10.0, 80.0, 40.0, 50.0]
    
    # -----------------------------------------------------------------
    # 案例 1：模拟正常运作的 First Fit 代码 (通过赋予极大优先级)
    # -----------------------------------------------------------------
    good_code = """
def priority_v2(item_size: float, remaining_space: float) -> float:
    # 无论物品大小或箱子空间，统一赋予极大优先级，使决策逻辑倾向于放入第一个能放得下的箱子
    return 1e6
    """
    program_1 = MockProgram(good_code)
    
    print("-> 测试案例 1：正常运作代码...")
    score_1, ok_1 = sandbox_instance.run(program_1, "entry_point", test_instance, 5)
    
    if ok_1:
        # 预期结果：正常评估，得出箱子数量 (分数小于 0)
        # 10个物品，大小各异，容量 100，First Fit 预期需要 ~5-6个箱子。分数预期是 -5 或 -6
        print(f"   [成功] 适应度分数 (负箱子数量): {score_1}\n")
    else:
        print(f"   [失败] {score_1}, {ok_1}\n")

    # -----------------------------------------------------------------
    # 案例 2：模拟运行时除以 0 错误的 LLM 代码
    # -----------------------------------------------------------------
    bad_code = """
def priority_v2(item_size: float, remaining_space: float) -> float:
    # 制造一个除以 0 的错误 (remaining_space 为 0 时出错，但模拟器会自动处理非法的 large)
    # 我们这里显式除以一个接近 0 的值
    return item_size / 0.0
    """
    program_2 = MockProgram(bad_code)
    
    print("-> 测试案例 2：除以零代码...")
    score_2, ok_2 = sandbox_instance.run(program_2, "entry_point", test_instance, 5)
    
    if not ok_2 and score_2 is None:
        # 预期结果： sandbox 返回错误并正确截获 None
        print("   [成功] 沙箱正确地拦截了生成的运行时错误，未崩溃。\n")
    else:
        print(f"   [失败] 预期返回 None, False。实际得到: {score_2}, {ok_2}\n")

    # -----------------------------------------------------------------
    # 案例 3：模拟死循环超时拦截
    # -----------------------------------------------------------------
    infinite_code = """
def priority_v2(item_size: float, remaining_space: float) -> float:
    # LLM 擅长写的死循环
    while True:
        pass
    return 0.0
    """
    program_3 = MockProgram(infinite_code)
    
    print("-> 测试案例 3：死循环超时测试 (等待 3 秒)...")
    # 设置短超时时间加速测试
    score_3, ok_3 = sandbox_instance.run(program_3, "entry_point", test_instance, 3)
    
    if not ok_3 and score_3 is None:
        # 预期结果：沙箱在 3s 时成功强制 kill 进程
        print("   [成功] 沙箱成功在 3 秒时终止了死循环代码运行。\n")
    else:
        print(f"   [失败] 预期超时拦截。实际得到: {score_3}, {ok_3}\n")