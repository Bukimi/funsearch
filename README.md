```markdown
# Sample-Efficient FunSearch for Online Bin Packing

本项目基于 DeepMind 的 **FunSearch** 框架，使用大型语言模型（LLM）自动进化在线一维装箱问题的启发式优先级函数。通过引入**语义去重缓存**和**安全沙箱评估**，实现了样本高效的搜索过程，显著减少了重复评估开销。

## 特性

- **在线装箱模拟器**：多进程安全沙箱中模拟 `First-Fit` 变体，根据 LLM 生成的优先级函数实时决策。
- **多层级代码去重**：基于 AST 规范化（变量重命名、交换律排序、关系符归一化）和语义微测试，识别并复用等价程序的历史得分。
- **FunSearch 进化管道**：单线程实现，包含岛屿模型、程序数据库、LLM 采样与评估器。
- **支持 OR-Library 数据集**：预置切换接口，可评估 20 个标准装箱实例。
- **丰富的统计指标**：记录 AST/语义命中率、评估轮次、时间开销和平均箱数。

## 项目结构

```
funsearch-main/implementation/
├── main.py                    # 主入口，冷启动与进化循环
├── funsearch.py               # FunSearch 官方入口（保留）
├── sampler.py                 # LLM 采样器（硅基流动 Qwen3-Coder）
├── evaluator.py               # 评估器，集成去重与沙箱调用
├── sandbox.py                 # 安全沙箱与装箱模拟器
├── deduplicator.py            # 多层级代码去重器
├── code_manipulation.py       # AST 操作工具
├── programs_database.py       # 岛屿数据库
├── config.py                  # 配置类
└── requirements.txt           # Python 依赖
```

## 安装

1. 克隆仓库并进入实现目录：
   ```bash
   git clone <repo-url>
   cd funsearch-main/implementation
   ```

2. 创建 Python 3.10+ 虚拟环境（推荐）：
   ```bash
   conda create -n funsearch python=3.11
   conda activate funsearch
   ```

3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
   核心依赖：`numpy`, `openai`, `absl-py`

## 配置与运行

在 `main.py` 中可调整关键参数：

- **LLM 设置**：`sampler.py` 中的 API 密钥、模型名称和温度。
- **数据集**：`load_bin_packing_dataset()` 函数可加载 OR3 或自定义文件。
- **进化参数**：`config_lib.Config` 中的岛屿数、采样数、评估超时等。

启动搜索：
```bash
python main.py
```
搜索将无限进行，按 `Ctrl+C` 安全终止并输出统计结果。

## 实验设置与评估指标

**数据集**：OR3 标准集，20 个实例，每个容器容量 150，首例物品数 500。

**指标体系**：

| 指标 | 说明 | 计算公式/来源 |
|------|------|--------------|
| 平均使用箱数 | 在所有测试实例上装箱的平均数量 | `-average(scores_per_test)` |
| L1 下界 | 理论最优下界（物品总体积/容量） | 需自行计算 |
| 超出百分比 | 实际箱数相对于下界的超出比例 | `(avg_bins - L1) / L1 * 100%` |
| AST 层级命中次数 | 仅通过 AST 规范化即命中缓存的次数 | `deduplicator.ast_hit_count` |
| 语义层级命中次数 | AST 未命中但微测试签名匹配的次数 | `deduplicator.semantic_hit_count` |

**时间性能**：

- **采样耗时**：LLM 单次生成代码的耗时（可在 `sampler.py` 记录并传入评估器）。
- **评估总耗时**：在 20 个测试实例上运行沙箱的总时间（已内置输出）。

## 运行示例

```
[System] 加载 OR3 数据集完成，共 20 个实例
✅ 初始种子代码评估成功！数据库已激活。
[System] 初始化完成！开始执行主搜索循环...
✅ 第 1 轮有效评估完成！
[Deduplicator] 🎯 Level-1 命中：AST 结构完全等价！
✅ 第 2 轮有效评估完成！
...
🛑 实验被手动终止。
📊 运行统计:
-> 去重库中总共收集了 10 个独立的启发式算法。
-> AST 层级命中: 58 次
-> 语义层级命中: 0 次
-> 平均得分: -212.00
🏁 总共完成 65 轮有效评估。
```

## 引用

如果本项目对你的研究有帮助，请引用 FunSearch 原论文：

> Bernardino Romera-Paredes et al. "Mathematical discoveries from program search with large language models." *Nature*, 2023.

