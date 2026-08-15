# MIT Course Catalog Scraper

Pulls every Course 6 (EECS) subject listing from
[catalog.mit.edu](http://catalog.mit.edu/subjects/6/) into a flat text file —
**423 course blocks** as of the last run.

```bash
pip install requests beautifulsoup4
python scrapper.py     # writes mit_courses.txt
```

Each block is the catalog's own `courseblock` div flattened to text — number,
title, units, prerequisites and description — separated by a rule:

```
6.3900 Introduction to Machine Learning Prereq: ... Units: 4-0-8 ...
--------------------------------------------------
```

## Status

**This is the data-collection step, not an advisor.** The repository name
describes the intended destination — an assistant that recommends courses from
the catalog — but none of that is built here. What exists is the scraper and
its output, which is the corpus such a system would need.

Reasonable next steps would be chunking each block, embedding it, and putting a
retrieval layer over the result so questions like "what should I take after
6.3900?" can be answered against the catalog rather than from memory.

## Limits

The scraper targets Course 6 only, has no rate limiting or retry, and depends on
the catalog's current `courseblock` markup — a redesign of the page will break
it. `mit_courses.txt` is a committed snapshot, so it reflects the catalog on the
day it was run, not today.
