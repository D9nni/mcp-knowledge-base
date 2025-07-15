from typing_extensions import Self
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from .types import BaseModel
import os


class HFModel(BaseModel):
    def __init__(self, name: str, model, tokenizer):
        self.name = name
        self.model = model
        self.tokenizer = tokenizer
        self.max_tokens = 1024
        self.generator = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device_map="auto"
        )

    @classmethod
    def from_pretrained(cls, model_id: str, **kwargs) -> Self:
        tokenizer = AutoTokenizer.from_pretrained(model_id, **kwargs)
        model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        return cls(name=model_id, model=model, tokenizer=tokenizer)

    def generate(self, prompt: str, **kwargs) -> str:
        if 'max_new_tokens' not in kwargs:
            kwargs['max_new_tokens'] = self.max_tokens

        outputs = self.generator(prompt, **kwargs)
        full_output = outputs[0]['generated_text']
        response = full_output[len(prompt):].strip()
        
        return response
