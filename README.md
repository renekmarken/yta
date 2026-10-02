# Site Review Studio

A free, cloud-run YouTube review factory for **high-RPM US websites and apps**:

**trend scan → ranked queue → web research → honest script → AI voice → uniquely designed 1080p video → thumbnail → SEO title/description/tags/chapters/captions**

Runs on GitHub Actions (free). Your PC can be off.

---

## How it works

**1. Discovery (every 3 hours).** Scans free trend sources for new and hot products in your 13 money categories:

- Gemini with Google Search, asked what launched or made news in the last 14 days
- Google News launch and funding searches, run per category
- Google Trends daily US searches
- Product Hunt launches and Hacker News "Show HN" posts
- Apple App Store top charts for Finance, Business and Productivity, including which apps are climbing

Gemini acts as the editor: it picks the products worth reviewing, finds each official website, assigns a category and scores hotness from 0 to 10. Every website is checked to exist before it goes into the queue.

**2. Priority.** `priority = 0.65 × hotness (halves every 4 days) + 0.35 × category value + 2 if fresh`.

- Category value comes from your RPM, evergreen and topic-count table in `studio/categories.py`. Tune the channel with `weight_boost`.
- New and hot products are reviewed first.
- An evergreen backlog of popular brands is kept for every category, so the queue never runs dry.
- The same category is never picked twice in a row.

See the live ranking in **`data/QUEUE.md`** on GitHub.

**3. Production (twice a day, or whenever you press Run).** For each video, the system:

- visits the site and takes clean screenshots (cookie banners and chat bubbles are hidden), pricing and fee pages, the mobile view and the logo
- researches the product on the web: who runs it, licences, fees, recent news and real user complaints, with sources
- writes a 2–3 minute script in one of 6 formats, follows a category checklist (for example renewal price for VPNs, FDIC partner bank for fintechs), avoids repeating openings from earlier videos and is quality-checked
- records the voice with free Microsoft neural voices, falling back to Piper offline if Microsoft blocks it
- renders the video with a **unique design**, a thumbnail, a captions file and an upload kit

### Every video looks different

Each video gets its own random combination, chosen to differ from the last few videos:

| Element | Options |
|---|---|
| Layout | full browser · side panel · stage · full-screen cinema |
| Colour mode | dark · brand-coloured · light, accent from the site's own logo or an alternate |
| Background | gradient · mesh · spotlight · grid · dots |
| Browser frame | macOS dark/light · floating card · minimal |
| Captions | accent bar · pill · numbered tag · underline |
| Headline font | Inter, Inter Display, Poppins, Archivo Black, Anton, Bebas Neue |
| Transitions | fade, slide, smooth, wipe, circle, zoom, blur, hard cut… |
| Intro card | logo pop · headline · split |
| Smart camera | zooms onto the exact number/button being discussed and highlights it (box, underline or spotlight) |
| Extras | progress bar, score ring or centred verdict end card |
| Thumbnail | tilted card · diagonal split · centred stack · phone · sticker |

Every thumbnail has the site's **logo**, its **name** and **"WORTH USING IT?"**.

---

## Set up (15 minutes, all free)

1. **Create a private GitHub repo** and upload everything from this zip, including the hidden `.github` folder. A private repo gets 2,000 free Actions minutes a month, which is enough for about 3 videos a day.
2. Go to **Settings → Secrets and variables → Actions → Secrets** and add:
   - `GEMINI_API_KEY`: your Gemini key. Both Google AI Studio keys and Vertex AI "AQ." keys work; the code tries both Google endpoints.
   - `NTFY_TOPIC` (optional): any hard-to-guess name. Install the free **ntfy** app and subscribe to that name to get a phone notification when videos are ready.
3. Optional **Variables** (same page, *Variables* tab): `VIDEOS_PER_RUN` (default 1), `CHANNEL_NAME`, `TTS_VOICE`.
4. Open the **Actions** tab and enable workflows. Run **Discover trending products** first, then **Produce review videos**.
5. Open the finished run and download the `videos-N.zip` file under **Artifacts**.

### Publish (about 2 minutes per video)

Each video folder contains `UPLOAD_KIT.md`, which holds the title, description (with chapters and sources), tags, pinned comment and a short list of claims to double-check.

1. In YouTube Studio, upload `video.mp4`.
2. Paste the title, description and tags from the kit.
3. Set `thumbnail.jpg` as the thumbnail and upload `captions.srt` under Subtitles.
4. Add one line of your own take, then publish.

That quick human pass is what keeps the channel eligible for monetization. YouTube's "inauthentic content" policy demonetizes whole channels that mass-upload unreviewed AI videos.

### Automatic upload (later, optional)

YouTube permanently locks videos uploaded through an unverified API project as private. To upload automatically:

1. Run `get_youtube_token.py` on your PC, following the steps inside it.
2. Add the `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and `YT_REFRESH_TOKEN` secrets.
3. Apply for the free audit: <https://support.google.com/youtube/contact/yt_api_form>.
4. After approval, set the variable `UPLOAD_MODE` = `api`. Videos then arrive on your channel as unlisted videos (change with the variable `YT_PRIVACY`), with their thumbnail and captions.

---

## Control it

| Want to… | Do this |
|---|---|
| Review a specific site next | Add its URL to `sites.txt` (pinned to the front), or *Run workflow* with a URL |
| More / fewer videos | Variable `VIDEOS_PER_RUN`, or change the `cron` times in `.github/workflows/produce.yml` |
| More of one category | Raise its `weight_boost` in `studio/categories.py` |
| See what's coming | `data/QUEUE.md` |
| See what was made | `data/history.json`, `data/done.txt`; blocked sites go to `data/failed.txt` |
| Different voice | Variable `TTS_VOICE` (e.g. `en-US-AvaMultilingualNeural`, `en-US-BrianNeural`) |
| Your channel badge on thumbnails | Add `assets/thumbnail_overlay.png` (1280×720, transparent) |
| Background music | Add `assets/music.mp3` (royalty-free, e.g. YouTube Audio Library) |

## On your PC (optional)

```bash
pip install -r requirements.txt && python -m playwright install chromium
python tools/get_fonts.py
cp .env.example .env              # add your Gemini key
python discover.py                # update the queue
python run.py                     # next video from the queue
python run.py --url https://www.chime.com
python run.py --restyle output/chime-com    # same review, new design
python run.py --rerender output/chime-com   # after editing script.json or recording your own voice
```

To use your own voice, record `voice/seg_00.mp3`, `seg_01.mp3`, … in a video's folder, deleting the AI files first, then run `--rerender`.

## Good to know

- Some big sites block automated browsers. They are detected, logged in `data/failed.txt` and skipped, and the queue moves on.
- Gemini's free tier has daily limits. One video uses about 2 requests and one discovery run about 3, which is well inside them.
- Custom thumbnails need a phone-verified YouTube channel (youtube.com/verify).
- Reviews show logos and screenshots for commentary. Keep them honest and balanced, and never imply a sponsorship that doesn't exist.
