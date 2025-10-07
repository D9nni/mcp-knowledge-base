from typing import AsyncGenerator
from .prompt import BasePrompt
from .model import BaseModel
from .client import MCPClientMaanger
from .types import AgentResponse
from . import errors
from . import utils
from typing import Any
import json
import re
import logging


SYSTEM_PROMPT = """You are a helpful assistant"""

#* Llama 3.2
TOOL_CALL_PROMPT = """You are an expert in composing functions. You are given a question and a set of possible functions. 
Based on the question, you may need to make one or more function/tool calls to achieve the purpose. 
If none of the function can be used, point it out. If the given question lacks the parameters required by the function,
also point it out. You should only return the function call in tools call sections.

You MUST return ONLY a single line containing a JSON-formatted list of function calls.
The expected output looks like this:
[
    {{"function": "func1", "params": {}}},
    {{"function": "func2", "params": {{"param1": 123, "param2": "abc"}}}}
]

If you do not respect this format exactly, your response will be considered invalid.

Example of valid response:
[{{"function": "get_weather", "params": {{"city": "London"}}}} ]

Example of INVALID response:
{{"function": "get_weather", "params": {{"city": "London"}}}}
(do not return a single object — always a list)

Here is a list of functions in JSON format that you can invoke.

{function_scheme}
"""

logger = logging.getLogger('agent')
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()

formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
handler.setFormatter(formatter)

logger.addHandler(handler)

class Agent:
    def __init__(self, name:str, model:BaseModel, prompt:BasePrompt) -> None:
        self.name:str = name

        self.llm:BaseModel = model
        self.prompt:BasePrompt = prompt

        self.mcp_manager = MCPClientMaanger()

        self.func_scheme_prompt = ""
        self.resource_prompt = ""

    @property
    def model_name(self):
        return self.llm.name
    
    @property
    def server_list(self):
        return self.mcp_manager.get_server_names()
    
    def register_mcp(self, config: dict[str, Any]):
        self.mcp_manager.register_mcp(config)

    async def init_agent(self):
        await self.mcp_manager.init_mcp_client()

        func_scheme_list = await self.mcp_manager.get_func_scheme()
        # resource_list = await self.mcp_manager.get_resource_list()

        self.func_scheme_prompt = json.dumps(func_scheme_list)
        # self.resource_prompt = json.dumps(resource_list)
        
        p = self.prompt.get_system_prompt(SYSTEM_PROMPT)
        self.prompt.set_system_prompt(p)

    async def clean_agent(self):
        await self.mcp_manager.clean_mcp_client()

    async def __aenter__(self):
        await self.init_agent()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.clean_agent()

    def _is_tool_required(self, response:str):
        try:
            json.loads(response)
            return True
        except json.JSONDecodeError:
            return False

    def get_func_props(self, response:str):
        return json.loads(response)

    async def get_result_tool(self, response:str) -> list[list[str]]:
        result_list = []
        for call in self.get_func_props(response):
            name = call['function']
            param = call['params']
            res = await self.mcp_manager.call_tool(name, param)
            is_err, content_list = res
            logger.debug(f"mcp function({name}) with param({param}) has results({content_list})")

            results = [c.text for c in content_list]

            result_list.append({'name':name, 'output':results})
        
        return result_list

    async def chat(self, question:str, **kwargs) -> list[AgentResponse]:
        response_list = []

        logger.debug(f"agent got question({question})")

        tool_scheme = TOOL_CALL_PROMPT.replace("{function_scheme}", self.func_scheme_prompt)
        
        p = self.prompt.get_user_prompt(question=question, tool_scheme=tool_scheme)
        self.prompt.append_history(p)
        gen_prompt = self.prompt.get_generation_prompt(tool_enabled=True, last=1)
        logger.debug("Using generation prompt ((" + gen_prompt + "))\n")
        response = self.llm.generate(gen_prompt, **kwargs)
        response = response.strip().lstrip('()<>\{\}`') #! remove noise (temporal)

        logger.debug(f"llm generated response ({response})")

        if self._is_tool_required(response):
            logger.debug(f"agent tool required")
            response_list.append(AgentResponse(type="tool-calling", data=response))

            p = self.prompt.get_assistant_prompt(answer=response)
            self.prompt.append_history(p)

            result = await self.get_result_tool(response)
            result = json.dumps(result, ensure_ascii=False)

            response_list.append(AgentResponse(type="tool-result", data=result))

            logger.debug(f"got result of each tool ({result})")

            p = self.prompt.get_tool_result_prompt(result=result)
            self.prompt.append_history(p)

            response = self.llm.generate(self.prompt.get_generation_prompt(tool_enabled=False, last=3), **kwargs)

            logger.debug(f"llm generated final response({response})")

        response_list.append(AgentResponse(type="text", data=response))

        p = self.prompt.get_assistant_prompt(answer=response)
        self.prompt.append_history(p)
        logger.debug("llm agent returned response list")
        return response_list

