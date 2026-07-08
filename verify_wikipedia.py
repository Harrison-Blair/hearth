import asyncio
from assistant.search.wikipedia import WikipediaSearch

async def verify():
    searcher = WikipediaSearch(max_snippet_chars=1000)
    queries = ["France"]
    
    for query in queries:
        print(f"Searching for: {query}")
        try:
            results = await searcher.search(query, count=5)
            if not results:
                print(f"  No results found for '{query}'")
            for i, res in enumerate(results):
                print(f"  [{i+1}] {res.title}")
                print(f"      URL: {res.url}")
                print(f"      Snippet: {res.snippet[:500]}...")
        except Exception as e:
            print(f"  Error searching for '{query}': {e}")
        print("-" * 20)
    await searcher.aclose()


if __name__ == "__main__":
    asyncio.run(verify())
