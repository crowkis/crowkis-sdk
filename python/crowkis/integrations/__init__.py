"""Framework integrations for Crowkis.

Import the one you need — third-party frameworks are optional dependencies:

    from crowkis.integrations.langchain import CrowkisCache   # needs crowkis[langchain]
    from crowkis.integrations.memory import CrowkisMemory      # no extra deps
    from crowkis.integrations.pipecat import crowkis_processors  # needs crowkis[pipecat]

`CrowkisMemory` is dependency-free and works in any agent framework
(LangGraph, CrewAI, AutoGen, or your own loop); it is also re-exported from
the top-level `crowkis` package.
"""
