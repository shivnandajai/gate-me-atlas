# GATE ME Atlas

GATE ME Atlas is a private website for GATE 2027 Mechanical Engineering preparation. It ranks every syllabus subject and topic by the marks it carried in 17 past papers (2016 to 2026), and its question bank holds all 1,105 questions of those papers with their options and diagrams. It also shows the official GATE 2027 important dates and the latest official notifications.

The dates and notifications update automatically twice a day. The updates run on GitHub's free service, so they do not depend on any Claude subscription.

## How the automatic updates work

1. A scheduled GitHub Actions workflow (`.github/workflows/update-official.yml`) runs at 7:59 AM and 7:59 PM India time.
2. The workflow first tests `scripts/update_official.py` on the sample pages in `tests/`. It then runs the script, which reads two public pages of the official website: the notifications page and the important dates page of https://gate2027.iitm.ac.in.
3. The script saves the two newest notifications and the current schedule in `data/official.json`. Dates that the official page shows as struck through are ignored.
4. The workflow then publishes the website. The website reads `data/official.json` every time it opens, so visitors always see the latest saved information.
5. If the official website cannot be read, or its layout changes so that the script cannot understand it, the script stops without changing the saved data. The website keeps showing the last good information, and GitHub sends an email about the failed run.

## Checking that it works

- In the Actions tab, every run shows a green tick if it worked and a red cross if it failed.
- On the website, the "checked" time in the Important dates panel should be less than about 12 hours old.

## Stopping or changing the schedule

- To stop the updates, open the Actions tab, click "Update GATE 2027 dates and news", click the "..." button, and choose "Disable workflow".
- To change the times, edit the `cron` line in `.github/workflows/update-official.yml`. GitHub uses UTC, which is 5 hours 30 minutes behind India time.

## Notes

- GitHub pauses scheduled workflows in public repositories that have had no activity for 60 days. This workflow saves the "checked" time on every run and also switches its own schedule back on, so it is not paused.
- The free GitHub Pages plan needs a public repository. The original PDF question papers are not in the repository.
- `tests/` holds sample pages with the same layout as the official pages, including struck-out old dates and the exam cell that spans three rows. Every run tests the script on them before it reads the official site. To test by hand, run `python tests/test_parser.py`.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The website's start page |
| `app.bin` | The website |
| `qb/<paper>.bin` | Question bank: one paper's questions, options and diagrams |
| `lock.json` | Settings the start page needs to open the website |
| `vendor/katex/` | KaTeX, which typesets the formulas (MIT licence, see `LICENSE.txt`) |
| `data/official.json` | Official GATE 2027 dates and notifications, refreshed by the workflow |
| `scripts/update_official.py` | Reads the official pages and writes `data/official.json` |
| `scripts/requirements.txt` | Python packages the script needs |
| `.github/workflows/update-official.yml` | The twice-daily schedule and the publishing steps |
| `tests/` | Sample pages and a test for the reader |
