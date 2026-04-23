# Copyright 2023 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Class for sampling new programs."""
from collections.abc import Collection, Sequence
import numpy as np
import openai
import re

import evaluator
import programs_database

import openai
from typing import Collection


class OpenAIFunSearchLLM:
    """使用 OpenAI 接口预测代码后续的语言模型类。"""

    def __init__(self, samples_per_prompt: int) -> None:
        self._samples_per_prompt = samples_per_prompt
        # 配置信息（请替换为您的有效 API 密钥和地址）
        self.api_key = "sk-..."
        self.host_url = "https://api.bltcy.ai"
        self.client = openai.OpenAI(
            base_url=f"{self.host_url}/v1",
            api_key=self.api_key,
            timeout=120,
        )

    def draw_samples(self, prompt: str) -> Collection[str]:
        """使用 OpenAI API 返回多个预测的代码后续。"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-5-nano",  # 请确认模型名称是否正确
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert Python coding assistant. Return ONLY raw Python code without markdown blocks or explanations."
                    },
                    {"role": "user", "content": prompt}
                ],
                n=self._samples_per_prompt,
                temperature=0.8,
            )
            # 直接返回 API 获取的内容，不进行额外清洗
            return [choice.message.content for choice in response.choices]
        except Exception as e:
            print(f"LLM Error: {e}")
            return []

class Sampler:
  """采样节点：获取 Prompt，调用 LLM 生成样本并发送给评估器。"""

  def __init__(
      self,
      database: programs_database.ProgramsDatabase,
      evaluators: Sequence[evaluator.Evaluator],
      samples_per_prompt: int,
  ) -> None:
    self._database = database
    self._evaluators = evaluators
    # 实例化 LLM 模块
    self._llm = OpenAIFunSearchLLM(samples_per_prompt)

  def sample(self):
    """持续获取 Prompts，采样程序并进行分析。"""
    while True:
      # 1. 从数据库中获取当前最优的 Prompt
      prompt = self._database.get_prompt()
      
      # 2. 调用 LLM 生成变体算法
      samples = self._llm.draw_samples(prompt.code)
      
      # 3. 将生成的代码分发给评估器
      for sample in samples:
        # 随机选择一个评估器（在单线程版本中通常只有一个）
        chosen_evaluator = np.random.choice(self._evaluators)
        chosen_evaluator.analyse(
            sample, 
            prompt.island_id, 
            prompt.version_generated
        )
