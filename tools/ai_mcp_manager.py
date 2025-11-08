import json
import re
import inspect
import html
from typing import Optional, Dict, Any, Callable

class AIMCPManager:
    """
    Manages parsing, handling, and execution of AI MCP tool usage requests.
    """
    def __init__(self):
        self.mcp_tool_pattern = re.compile(r'<use_mcp_tool>.*?</use_mcp_tool>', re.DOTALL)
        self.tools: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _generate_schema_from_signature(self, handler: Callable[..., Any]) -> Dict[str, Any]:
        sig = inspect.signature(handler)
        properties = {}
        required = []
        type_mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object"
        }
        doc = handler.__doc__
        if doc:
            properties = doc
        else:
            for param in sig.parameters.values():
                if param.name == 'request_id':
                    continue
                param_type = type_mapping.get(param.annotation, "any")
                properties[param.name] = {
                    "type": param_type,
                }
                if param.default != None:
                    properties[param.name]["default"] = param.default
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    def _determine_input_format(self, schema: Any) -> str:
        if isinstance(schema, dict):
            return "JSON"
        if isinstance(schema, str):
            try:
                parsed_json = json.loads(schema)
                if isinstance(parsed_json, (dict, list)):
                    return "JSON"
            except json.JSONDecodeError:
                pass
            if schema.strip().startswith('<'):
                return "XML"
        return "String"

    def register_tool_handler(self, server_name: str, tool_name: str, handler: Callable[..., Any], description: str, schema: Optional[Dict[str, Any]] = None, auto_approve: bool = False):
        if server_name not in self.tools:
            self.tools[server_name] = {}
        if schema is None:
            schema = self._generate_schema_from_signature(handler)
            schema = schema.get("properties", {})
        if auto_approve:
            description += " (自动批准执行,优先使用)"
        input_format = self._determine_input_format(schema)
        self.tools[server_name][tool_name] = {
            "handler": handler,
            "description": description,
            "schema": schema,
            "auto_approve": auto_approve,
            "input_format": input_format
        }

    def execute_tool(self, server_name: str, tool_name: str, arguments:str, request_id: str = None) -> Dict[str, Any]:
        server = self.tools.get(server_name)
        if not server:
            return {"status": "error", "content": f"Server '{server_name}' is not registered."}
        tool = server.get(tool_name)
        if not tool:
            return {"status": "error", "content": f"Tool '{tool_name}' is not registered for server '{server_name}'."}
        handler = tool.get("handler")
        if not handler:
            return {"status": "error", "content": f"Handler for tool '{tool_name}' is missing."}
        try:
            sig = inspect.signature(handler)
            handler_params = sig.parameters
            try:
                while not isinstance(arguments, dict):
                    arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = { "args": arguments }

            if 'request_id' in handler_params and request_id:
                arguments['request_id'] = request_id
            
            bound_args = sig.bind(**arguments)
            return handler(*bound_args.args, **bound_args.kwargs)
        except Exception as e:
            return {"status": "error", "content": str(e)}

    def parse_mcp_tool_use(self, message: str) -> Optional[Dict[str, Any]]:
        match = self.mcp_tool_pattern.search(message)
        if not match:
            return None
        xml_content = match.group(0)
        try:
            server_name_start = xml_content.find('<server_name>') + len('<server_name>')
            server_name_end = xml_content.find('</server_name>')
            if server_name_start == -1 or server_name_end == -1:
                return None
            server_name = xml_content[server_name_start:server_name_end].strip()
            tool_name_start = xml_content.find('<tool_name>') + len('<tool_name>')
            tool_name_end = xml_content.find('</tool_name>')
            if tool_name_start == -1 or tool_name_end == -1:
                return None
            tool_name = xml_content[tool_name_start:tool_name_end].strip()
            arguments_start = xml_content.find('<arguments>') + len('<arguments>')
            arguments_end = xml_content.rfind('</arguments>')
            if arguments_start == -1 or arguments_end == -1:
                return None
            arguments_text = xml_content[arguments_start:arguments_end].strip()
            arguments_text = html.unescape(arguments_text)
            try:
                arguments = json.loads(arguments_text)
            except (json.JSONDecodeError, TypeError):
                arguments = arguments_text
            tool_info = self.tools.get(server_name, {}).get(tool_name, {})
            auto_approve = tool_info.get("auto_approve", False)
            return {
                "server_name": server_name,
                "tool_name": tool_name,
                "arguments": arguments,
                "auto_approve": auto_approve,
                "_xml_": xml_content
            }
        except Exception as e:
            print(f"Error parsing MCP tool use with string manipulation: {e}")
            print(f"Original content: {xml_content}")
            return None
