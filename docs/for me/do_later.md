
Implemented the speed improvements I think are worth keeping right now.

In [processing.py](/Users/moritzvitt/src/addons/ai-automation/processing.py), note processing now uses async orchestration with bounded concurrency via `asyncio` plus `asyncio.to_thread(...)`, instead of the older batch-by-batch thread-pool loop. That keeps more note requests in flight efficiently while still respecting your configured parallelism limit.

I also changed note writes to bulk updates where possible in [processing.py](/Users/moritzvitt/src/addons/ai-automation/processing.py), using `mw.col.update_notes(...)` instead of updating each changed note one by one. That should reduce collection-write overhead noticeably on larger runs.

For workflow groups, the behavior remains strictly sequential by design, and I made that explicit in [workflow_ui.py](/Users/moritzvitt/src/addons/ai-automation/workflow_ui.py): one workflow runs fully, then the next starts. So multiple workflows can safely touch the same notes without racing each other.

Verification: `python3 -m py_compile *.py` passed.

If you want, the next step could be measuring this with a real batch and then tuning `max_parallel_requests` based on where your rate limits start showing up.

I mean this:

`max_parallel_requests` controls how many notes we try to send to the API at the same time within one workflow/run.

Example:
- `1` = fully sequential, safest, slowest
- `3` = up to 3 note requests at once
- `8` = faster if the API/provider can handle it, but more likely to hit rate limits or temporary failures

So the practical way to tune it is:
1. run a real batch you actually use, for example 30-100 notes
2. start with something like `3`
3. if it finishes cleanly, try `4` or `5`
4. if you start seeing `429`, retries, or flaky failures, back it down

What “measuring” means here:
- compare total runtime for the same batch at different settings
- watch whether errors increase
- pick the highest setting that is still stable for your model/account

So the goal is not “set it as high as possible”.
The goal is:
- as much parallelism as your OpenAI tier/model tolerates
- without making runs unreliable

A reasonable default progression would be:
- `3` -> `5` -> `8`
- stop increasing once failures/retries start becoming common

If you want, I can also add:
- a safer config description in [config.md](/Users/moritzvitt/src/addons/ai-automation/config.md)
- or runtime stats/logging so you can actually see how long each batch took and how many retries happened