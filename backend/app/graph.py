import asyncio
from .graph_builder import build_graph, init_runtime

runtime = asyncio.run(
    init_runtime()
)

graph = build_graph(runtime)
