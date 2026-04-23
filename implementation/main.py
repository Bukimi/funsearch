import sys
import time

# 导入 FunSearch 官方内部组件
import code_manipulation
import programs_database
import config as config_lib

# 导入你的自定义组件 (注意检查 sampler 和 evaluator 的路径是否正确)
from deduplicator import CodeDeduplicator
import bin_packing_utils
# 如果你的 sampler.py 和 evaluator.py 直接覆盖了官方文件，可以这样导入：
from sampler import Sampler
from evaluator import Evaluator


def load_bin_packing_dataset():
    """加载 OR3 全部 20 个实例，返回 (test_inputs, capacity)"""
    or3_dict = bin_packing_utils.datasets['OR3']
    test_inputs = []
    capacity = None
    for inst_data in or3_dict.values():
        items = inst_data['items']
        cap = inst_data['capacity']
        if capacity is None:
            capacity = cap
        else:
            assert capacity == cap, "所有实例容量应相同"
        test_inputs.append(items)
    return test_inputs, capacity

def main():
    print("======================================================")
    print("🚀 启动 Sample-efficient FunSearch 流水线")
    print("======================================================")
    
    print("\n[System] 正在评估初始代码模板并激活数据库岛屿...")
    
    # ====================================================================
    # 【最纯净的骨架模板】
    # ====================================================================
    template_string = (
        "import math\n\n"
        "def priority_v1(item_size: float, remaining_space: float) -> float:\n"
        "    return 1.0\n\n"
        "def priority_v2(item_size: float, remaining_space: float) -> float:\n"
        "    return 1.0\n"
    )
    
    # 转换为 AST Program 对象
    template_program = code_manipulation.text_to_program(template_string)

    # ====================================================================
    # 【2. 加载数据集与配置初始化】
    # ====================================================================
    test_inputs , bin_capacity= load_bin_packing_dataset()
    print(f"[System] 加载 OR3 数据集完成，共 {len(test_inputs)} 个实例，"
          f"每个容量 = {bin_capacity}，第一个实例物品数 = {len(test_inputs[0])}")
    # 初始化 FunSearch 数据库专用的配置子项
    db_config = config_lib.ProgramsDatabaseConfig(
        num_islands=1,
        reset_period=4 * 60 * 60,
        functions_per_prompt=2
    )
    # 将子项包装进主配置类中
    config = config_lib.Config(
        programs_database=db_config,
        num_samplers=1,      # 单机运行设为 1
        num_evaluators=1,    # 单机运行设为 1
        samples_per_prompt=4
    )

    # ====================================================================
    # 【3. 实例化核心组件】（确保使用刚刚生成的 template_program）
    # ====================================================================
    # 实例化数据库
    database = programs_database.ProgramsDatabase(
        config=config.programs_database, 
        template=template_program,
        function_to_evolve="priority_v2"
    )

    # 实例化 AST 去重器
    deduplicator = CodeDeduplicator()
    
    # 实例化评估器 
    test_inputs, bin_capacity = load_bin_packing_dataset()
    evaluator_instance = Evaluator(
        database=database,
        template=template_program,
        function_to_evolve="priority_v2",
        function_to_run="priority_v2",
        inputs=test_inputs,
        timeout_seconds=30,
        deduplicator=deduplicator,
        bin_capacity=bin_capacity
    )
    
    # 实例化采样器
    sampler = Sampler(
        database=database,
        evaluators=[evaluator_instance],
        samples_per_prompt=4 # 每次让大模型生成 4 个变体
    )

    # ====================================================================
    # 【4. 冷启动：纯净版初始种子】
    # ====================================================================
    initial_code = """    return 1.0"""
    
    # 直接跳过沙箱，手动给种子打分并存入数据库（或者运行一次评估）
    # 这里我们还是运行评估，但确保传入的是完整的代码结构
    evaluator_instance.analyse(
        sample=initial_code,  # 现在这里只包含 Body
        island_id=0,          # 明确给第一个岛屿
        version_generated=None
    )

    # ====================================================================
    # 【5. 启动自循环流水线】
    # ====================================================================
    # 确保冷启动真的成功了
    if not database._islands[0]._clusters:
        print("❌ 致命错误：初始种子代码评估失败，未能存入数据库！请检查沙箱是否报错。")
        sys.exit(1)
    else:
        print("✅ 初始种子代码评估成功！数据库已激活。")

    print("\n[System] 初始化完成！开始执行主搜索循环...")
    print("提示：按 Ctrl+C 可以随时安全终止实验。\n")
    
    try:
        # 启动无限进化循环
        sampler.sample()
        
    except KeyboardInterrupt:
        from evaluator import evaluation_round  # 导入计数器
        print("\n======================================================")
        print("🛑 实验被手动终止。")
        print("📊 运行统计:")
        # 打印命中率数据，直接支撑你论文中的核心论点
        if hasattr(deduplicator, '_seen_ast_hashes'):
            cache_size = len(deduplicator._seen_ast_hashes)
            print(f"-> 去重库中总共收集了 {cache_size} 个独立的启发式算法。")
        print("======================================================")
        # 新增：输出去重命中统计
        if hasattr(deduplicator, 'ast_hit_count'):
            total_hits = deduplicator.ast_hit_count + deduplicator.semantic_hit_count
            print(f"-> AST 层级命中: {deduplicator.ast_hit_count} 次")
            print(f"-> 语义层级命中: {deduplicator.semantic_hit_count} 次")
            print(f"-> 总命中次数: {total_hits} 次")
            print(f"🏁 总共完成 {evaluation_round} 轮有效评估。")
        print("======================================================")
        sys.exit(0)

if __name__ == "__main__":
    # Windows/Mac 下多进程沙箱的安全启动限制
    import multiprocessing
    multiprocessing.freeze_support()
    main()