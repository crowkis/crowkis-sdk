"""Semantic LLM cache for LangChain (and LangGraph) in two lines.

    pip install crowkis[langchain]
    docker run -p 6379:6379 -v "$(pwd)/.crow:/data/.crow" crowkis/crowkis:latest \
        server --data /data/.crow

Unlike LangChain's built-in caches (exact string match), Crowkis matches on
MEANING — so rephrased prompts hit the cache and you stop paying twice.
A single set_llm_cache(...) also covers LangGraph, since it runs on LangChain LLMs.
"""

from langchain_core.globals import set_llm_cache

from crowkis.integrations.langchain import CrowkisCache

# One line: every LangChain LLM / chat-model call now checks Crowkis first.
set_llm_cache(CrowkisCache(tenant="langchain-demo", ttl=3600))

# Then use LangChain exactly as you already do, e.g.:
#
#   from langchain_openai import ChatOpenAI
#   llm = ChatOpenAI(model="gpt-4o-mini")
#   print(llm.invoke("What is the capital of France?").content)      # miss → cached
#   print(llm.invoke("France's capital city — what is it?").content) # semantic HIT
