import warnings
import os

import tiktoken
from PIL import Image

from .base_engine import BaseOpenAIEngine, BaseOpenAIImageEngine

Image.MAX_IMAGE_PIXELS = None


class OpenAIEngine(BaseOpenAIImageEngine, BaseOpenAIEngine):
    def __init__(
        self,
        model_name,
        system_prompt: str = "You are helpful assistant",
        do_logprobs: bool = False,
        tokens_highlighted: list[str] = [],
        add_args: dict = {},
        wait_time: float = 60.0,
        attempts: int = 30,
    ) -> None:
        api_key_name = "OPENAI_KEY"
        super().__init__(
            model_name, system_prompt, add_args, wait_time, attempts, api_key_name
        )
        self.name = "openai/" + model_name
        # 允许通过环境变量覆盖 OpenAI 兼容网关地址，便于复用本地部署模型服务。
        self.model_url = os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"
        )
        # qwen-image 系列在部分兼容网关上要求首条消息为 user，且 content 为多模态列表。
        # 因此这里去掉 system 消息，避免请求被网关校验拒绝。
        if "qwen-image" in str(model_name).lower():
            self.payload["messages"] = []
            self.force_user_first_multimodal = True
        if do_logprobs:
            self.construct_logit_args(tokens_highlighted)
        self.tokens_highlighted = tokens_highlighted

    def construct_logit_args(
        self, tokens_highlighted: list[str] = [], logit_bias_value: float = 30.0
    ) -> None:
        tokenizer = tiktoken.encoding_for_model(self.name)

        options_tok_ids = dict()
        logit_bias = dict()

        for opt in tokens_highlighted:
            tok_ids = tokenizer.encode(opt)
            if len(tok_ids) == 1:
                warnings.warn(
                    "Output shpuld be 1 token length. We'll take only the first token"
                )
            logit_bias[tok_ids[0]] = logit_bias_value
            options_tok_ids[opt] = tok_ids

        self.args.update({"logit_bias": logit_bias})
