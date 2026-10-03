# Site Review Studio

A free, cloud-run YouTube review factory for **high-RPM US websites and apps**:

**trend scan → ranked queue → web research → honest script → AI voice → uniquely designed 1080p video → thumbnail → SEO title/description/tags/chapters/captions**

Runs on GitHub Actions (free). Your PC can be off.

---

## How it works

**1. Discovery (every hour), new launches first.** Scans free sources for products launched **today or this
week**, plus hot products, in your 13 money categories:

- Launch radar: Product Hunt launches, "Launch HN" (YC startups), TechCrunch startups, and Google News
  "launches / unveils / debuts" searches from the last day
- Gemini with Google Search, asked what launched or made news in the last 14 days
- Google News launch and funding searches, run per category
- Google Trends daily US searches
- Product Hunt launches and Hacker News "Show HN" posts
- Apple App Store top charts for Finance, Business and Productivity, including which apps are climbing

Gemini acts as the editor: it picks the products worth reviewing, finds each official website, assigns a category, scores hotness from 0 to 10 and marks what launched today / this week. Every website is checked to exist before it goes into the queue.

New launches jump to the top of the queue (launched today: +8 priority, this week: +5, fading over a few
days). If a fresh launch is hot enough, the discovery run **starts its video immediately**; it lands in
your library and you get a phone notification. Limits, as repository variables: `AUTO_VIDEOS_PER_DAY`
(default 3, `0` turns this off) and `AUTO_MIN_HOTNESS` (default 6).

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
| Layout | **tilt** (signature: tilted website card that gently sways, with a two-colour glow halo) · full browser · side panel · stage · spotlight |
| Light & glow | glow halo behind every website card and phone, soft light drifting across the background, glow behind the verdict |
| Colour mode | dark · brand-coloured · light, accent from the site's own logo or an alternate |
| Background | clean only: soft gradient · mesh · glow · aurora · blurred site, with fine film grain |
| Browser frame | macOS dark/light · floating card · minimal |
| Captions | accent bar · pill · numbered tag · underline · frosted glass, with a matching icon; animated in (slide up, drop, slide left/right, fade) |
| Callout stickers | the key fact of a segment ("$0 monthly fee", "4.30% APY") pops in with an icon on the top edge of the site, never over its text: card · pill · glass |
| Headline font | Inter, Inter Display, Poppins, Archivo Black, Anton, Bebas Neue |
| Transitions | fade, slide, smooth, wipe, circle, radial, cover/reveal, squeeze, zoom, blur, hard cut… |
| Intro card | logo pop · headline · split, animated (cards slide in, logo pops, title lines rise) |
| Smart camera | zooms onto the exact number/button being discussed and highlights it (box, underline or spotlight) |
| Extras | progress bar; animated verdict end card (score counts up, ring or bar fills) |
| Music | original track composed for each video: lofi · upbeat · ambient · tech · acoustic, new key/tempo/chords every time, ducked under the voice |
| Sound effects | 24 synthesised effects in 8 packs (soft, crisp, punchy, airy, digital, warm, minimal, playful), each tuned differently per video, levelled to the same quiet volume under the voice |
| Thumbnails | **3 options per video**, each a different layout, colour and hook. 8 clean layouts: centre stack, YES/NO split, logo + phone, half-screen site, score ring, laptop + phone, big real number, website banner; 8 saturated single-colour backgrounds; big logo badge, huge Anton hook with one yellow word, yellow label |

Every thumbnail uses one saturated colour built from the site's own blurred screenshot, the product's **logo** on a big white badge, crisp real screenshots (or the phone app), and a huge hook in Anton (white, black outline, one yellow word): "IS IT WORTH IT?", "IS IT A SCAM?",
"LEGIT OR HYPE?", "WHAT'S THE CATCH?"... Option 1 matches the video's title. Every item is measured and checked so
nothing important overlaps anything else or sits under YouTube's duration badge. Pick your favourite in the library;
automatic API uploads use a random one of the three.

Every video, thumbnail and download (zip) has **911video** in its file name.

---

## Set up (15 minutes, all free)

1. **Create a private GitHub repo** and upload everything from this zip, including the hidden `.github` folder. A private repo gets 2,000 free Actions minutes a month, which is enough for about 3 videos a day.
2. Go to **Settings → Secrets and variables → Actions → Secrets** and add:
   - `GEMINI_API_KEY`: your Gemini key. Both Google AI Studio keys and Vertex AI "AQ." keys work; the code tries both Google endpoints.
   - `NTFY_TOPIC` (optional): any hard-to-guess name. Install the free **ntfy** app and subscribe to that name to get a phone notification when videos are ready.
3. Optional **Variables** (same page, *Variables* tab): `VIDEOS_PER_RUN` (default 1), `CHANNEL_NAME`, `TTS_VOICE`.
4. Open the **Actions** tab and enable workflows. Run **Discover trending products** first, then **Produce review videos**.
5. Open your **private video library**: https://renekmarken.github.io/yta/videos/ (password-protected). Every video has download buttons, copy boxes for title/description/tags, an **Upload to YouTube** button, and **＋ Generate new videos** at the top.

### Publish (about 2 minutes per video)

Each video folder contains `UPLOAD_KIT.md`, which holds the title, description (with chapters and sources), tags, pinned comment and a short list of claims to double-check.

1. In YouTube Studio, upload the `.mp4`. It is named after the video's title, so Studio fills the title in for you.
2. Paste the title, description and tags from the kit.
3. Set one of the three `911video-thumbnail-N.jpg` files as the thumbnail and upload `captions.srt` under Subtitles.
4. Add one line of your own take, then publish.

That quick human pass is what keeps the channel eligible for monetization. YouTube's "inauthentic content" policy demonetizes whole channels that mass-upload unreviewed AI videos.

### Automatic upload (later, optional)

YouTube permanently locks videos uploaded through an unverified API project as private. To upload automatically:

1. Run `get_youtube_token.py` on your PC, following the steps inside it.
2. Add the `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and `YT_REFRESH_TOKEN` secrets.
3. Apply for the free audit: <https://support.google.com/youtube/contact/yt_api_form>.
4. After approval, set the variable `UPLOAD_MODE` = `api`. Videos then arrive on your channel as unlisted videos (change with the variable `YT_PRIVACY`), with their thumbnail and captions.

---

### The private video library

Everything in the library is encrypted with your password (GitHub secret `LIBRARY_PASSWORD`): the list
of videos *and* the files themselves (kept encrypted on the repo's `vault` branch). The page unlocks them in
your browser. The buttons that start GitHub runs use a token (secret `DISPATCH_TOKEN`, a fine-grained
token with *Actions: read and write* on this repo only) that is stored inside the encrypted data.
After changing either secret, run **Actions → Update the video library**. The newest 150 videos keep
their files (`LIBRARY_KEEP` variable).

How finished videos get in: every video run keeps its files as temporary `911video-…` downloads and
then starts **Update the video library**, the only workflow that writes to the library. It adds each
video with its 3 thumbnails, captions and upload kit, checks that GitHub really saved the encrypted
files, and only then deletes the temporary downloads (kept 7 days otherwise). It also runs every hour
as a safety net, so a video left behind by a failed step is picked up automatically. Two library
updates can never overwrite each other's files: a save that would is refused and retried later.

### Risk Case videos (second format)

**⚠ Generate Risk Case** in the library (or *Make a batch of videos* with *kind = risk*) makes a different
kind of video: one real person's worst experience with a popular product, explained, to raise awareness of
the risk (not to attack the product).

1. Takes popular products from the queue and past reviews (one Risk Case per product, never the same story twice).
2. Searches public posts: Reddit, Hacker News and news ("<brand> froze my account", "closed my account",
   "won't refund"...). Gemini picks the strongest real, specific story by number, so it can't invent one.
3. Investigates the whole story: reads the full thread (the complete post, the poster's own updates, the top
   replies) and notes similar public reports.
4. The video: the story told in full (the post shown on 2-4 cards with its real text, then the poster's update
   or a top reply), attributed to the platform only ("a Stripe user posted on Reddit...", never the subreddit
   or username), why it can happen, how to avoid it, what to do if it happens (support, appeal, chargeback,
   CFPB/BBB...), and a fair close.
5. Title straight from the story, e.g. "Stripe FROZE $50,000 for Over a Year — What Now?". The description links
   the original post and says it is one person's account.
6. Its own thumbnail styles, every option showing the post: big logo, huge glowing damage text
   ("$50,000 GONE."), "WHAT HAPPENED?" with a symbol that fits the story (lock = frozen, no-entry = banned,
   shield = hacked, $ = charges, gavel = legal). Option 1 is always the post card tilted on the right;
   option 2 is one of the black/dark styles (blackout: the post in dark mode with a symbol badge; stamp: a red
   "FROZEN" rubber stamp; caution: yellow words between caution tape; strip: the quote huge on a paper strip);
   option 3 is any other style (headline, phone app view, highlighted quote, or the post with the poster's
   update / top reply stacked in front). Most styles mark the post's key quote in yellow highlighter.

**Your own Risk Cases:** in the ⚠ Generate Risk Case dialog, fill in any app, product or website and the
issue to look for (e.g. "Instagram" + "users getting banned for no reason"; "＋ Add another" for more, up to
10). It finds the product's website, searches real users' posts about exactly that issue, and makes the
video the same way. These are made even for products that already had a Risk Case.

Always read the original post before publishing (it's the first item in the video's checklist).

### White Screen videos (third format)

**＋ Generate White Screen** in the library makes 35-45 second videos built for likes and comments: a
voice talks straight to the viewer while the words pop up one by one, centred, in big black Airone
letters on a plain white 16:9 screen (perfectly in time with the voice), with a few icons (like,
comment, trash, lock, hourglass...) and simple sound effects at the key words. No music.

- **It makes everything itself:** titles come from a queue of proven formats
  (`studio/ws_script.py`, editable in `data/whitescreen_titles.json`), where [Private Video],
  [Deleted Video] and the other attention-grabbing ones come up more often; a title can come back,
  with a fresh script (different goal, comment word and twist).
- **Or give it your own:** a title, a topic/instructions, or both ("＋ Add another" for more).
- Scripts follow the channel's own examples (`assets/whitescreen/examples.md`) and today's date, so
  "I'll bring it back in November" makes sense; never promises money or prizes.
- 3 thumbnails per video in the channel's styles: the sad/locked/glitched YouTube face for
  [Bracket] titles, YouTube-interface mock-ups ("0 Comments", the like bar, "Delete your channel?")
  with a red ring and arrow, the masked blue-hoodie character big on one half with 1-3 huge words,
  a headline style, a big-icon style and a white style.
- Assets: `assets/whitescreen/characters` (27 emotions cut out of your sheet),
  `assets/whitescreen/ytfaces` (30 red YouTube faces from your sheet), crisp icons, arrows and YouTube
  interface drawn in code (Roboto, YouTube's own font). **White Screen: improve assets** (Actions)
  redraws the character in full quality with Gemini's image model and adds new poses.

### Make many videos at once

**Actions → Make a batch of videos → Run workflow** (or **＋ Generate new videos** in the library) asks
*how many videos* (0–30), an optional *website to review* and *how many at the same time* (1–4). It picks
that many products from the queue (never one already reviewed), adds the website you typed in (made even
though it isn't in the queue), makes them in parallel and puts them all in the library.
Example: 10 videos, 3 at a time ≈ 35–45 minutes. Remember YouTube's daily upload limits and that posting
many AI-made videos a day can put monetisation at risk.

## Control it

| Want to… | Do this |
|---|---|
| Review a specific site next | Add its URL to `sites.txt` (pinned to the front), or *Run workflow* with a URL |
| More / fewer videos | Variable `VIDEOS_PER_RUN`, or change the `cron` times in `.github/workflows/produce.yml` |
| More of one category | Raise its `weight_boost` in `studio/categories.py` |
| See what's coming | `data/QUEUE.md` |
| See what was made | `data/history.json`, `data/done.txt`; blocked sites go to `data/failed.txt` |
| Never repeat a product | Automatic. Every reviewed (or blocked) product is kept forever in `data/reviewed.json`; Gemini is told never to suggest them, and the queue, `sites.txt` and manual URLs skip them (same website on any page/subdomain, or same name). To redo one on purpose, run locally with `python run.py --url ... --force` |
| Different voice | Variable `TTS_VOICE` (e.g. `en-US-AvaMultilingualNeural`, `en-US-BrianNeural`) |
| Your channel badge on thumbnails | Add `assets/thumbnail_overlay.png` (1280×720, transparent) |
| Background music | Composed automatically. Variable `MUSIC` = `off`, or one mood (`lofi`, `upbeat`, `ambient`, `tech`, `acoustic`) for every video. Your own track: add `assets/music.mp3` |
| Sound effects | On by default. Variable `SFX` = `0` turns them off |

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
- Gemini's free tier has daily limits. One video uses about 2 requests and one discovery run about 3 (24 runs a day), which is well inside them.
- Custom thumbnails need a phone-verified YouTube channel (youtube.com/verify).
- Reviews show logos and screenshots for commentary. Keep them honest and balanced, and never imply a sponsorship that doesn't exist.
