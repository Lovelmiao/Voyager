import yaml


class ToolManager:

    def __init__(self, mcp_manager):
        self.mcp_manager = mcp_manager
        self.runtime_tools = {}
        self.agent_permissions = {}

    def initialize(self, tool_registry_file, permission_file):
        self.runtime_tools = {
            t.name: t
            for t in self.mcp_manager.get_tools()
        }

        with open(permission_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.agent_permissions = {agent: set(info["tools"]) for agent, info in config["agents"].items()}

    async def refresh(self):
        await self.mcp_manager.refresh_tools()
        self.runtime_tools = {t.name: t for t in self.mcp_manager.get_tools()}

    def get_tools(self, agent_name):
        tool_names = self.agent_permissions.get(agent_name, set())
        return [self.runtime_tools[name] for name in tool_names if name in self.runtime_tools]

        def get_tool(self, name):
            return self.runtime_tools.get(name)
