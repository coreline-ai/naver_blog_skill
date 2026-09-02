# Visual Composition Workflow

Read this reference only when the user explicitly requests image planning, image generation, or images inserted into a Naver Blog draft.

## 1. Choose the operating mode

| Request | Mode | Result |
|---|---|---|
| “이미지 위치와 아이디어만 제안해줘” | `plan-only` | Slot plan, prompts, alt text, captions; no generation |
| “대표 이미지와 본문 이미지를 만들어 넣어줘” | `generate-and-compose` | Generated files, manifest, QA, composed Markdown |
| “이 사진 배경만 바꿔줘” | `edit-existing` | Preserve the target image and use an edit flow |
| No explicit image request | Text-only | Do not create a visual plan or call image generation |

Do not infer permission to generate images from an ordinary writing request. Do not publish to Naver or operate a logged-in editor unless the user separately requests and authorizes that action.

## 2. Lock the article before visual planning

Complete the article's factual review first. Images should support stable text, not text that may still change.

Before selecting slots, confirm:

- The title and section order are final enough to compose.
- Claims that need current sources have been verified.
- Facts, observations, opinions, and recommendations are distinguishable.
- The article does not describe generated scenes as the author's real evidence.

If a later factual edit changes a section's meaning, re-evaluate the affected slot instead of keeping a now-misleading image.

## 3. Extract visual beats

Identify moments where an image adds information or controls the emotional pace. A visual beat should perform at least one function:

- `orient`: establish the article's situation, place, person, or time
- `explain`: make a process, timeline, comparison, or system easier to understand
- `evidence`: show a real user-supplied screenshot, product, receipt, or place
- `contrast`: make a meaningful before/after or advantage/disadvantage distinction visible
- `transition`: mark a substantial shift in topic or emotional temperature
- `summarize`: reinforce a practical checklist or final decision frame

Do not add a slot when the image would merely repeat the heading, duplicate a nearby image, or act as decoration without new value. Do not force an image under every heading or derive a fixed count from article length.

## 4. Select slots

### Cover slot

Place the cover marker immediately after the H1 title. The cover should compress the article's core situation and emotional tone rather than reproduce the entire title as text.

```md
# 퇴근 후에도 국내 주식 거래가 가능할까요?

<!-- naver-image:cover -->
```

### Inline slots

Place an inline marker after the short paragraph that introduces the visual question, or immediately after a heading when the visual is needed before the explanation.

```md
## 거래시간은 어떻게 나뉠까요?

거래시간은 프리마켓, 메인마켓, 애프터마켓으로 나뉩니다.

<!-- naver-image:trading-hours -->
```

Use lowercase ASCII IDs containing letters, digits, and hyphens. Keep IDs semantic and unique within the article.

## 5. Build a consistency brief

Before prompting individual slots, define one shared visual brief:

- article mood and emotional temperature
- intended reader distance
- primary and accent palette
- realism or illustration level
- recurring person attributes, if any
- time of day, season, and location cues
- camera distance or graphic density
- mobile crop priority
- prohibited elements such as logos, in-image text, evidence-like documents, or money imagery

Use the confirmed writing profile as an input. For example, a bright but balanced reviewer voice may use natural light, restrained green accents, realistic textures, and uncluttered composition. Do not modify the profile file merely because a visual brief was created.

## 6. Choose the visual mode and write prompts

Read [`image-generation-modes.md`](image-generation-modes.md). Choose the mode separately for each slot while preserving the shared brief.

Each prompt should state:

1. use case and asset role
2. section purpose
3. scene or information structure
4. subject and meaningful details
5. medium or generation mode
6. composition and mobile crop behavior
7. lighting, mood, and palette
8. exact text only when essential
9. factual, brand, and identity constraints
10. avoid list for likely failure modes

Do not add invented people, events, products, or claims that the article does not imply.

## 7. Generate and persist files

For project-bound images:

1. Generate one distinct asset per slot.
2. Inspect the returned image before accepting it.
3. Copy the accepted image into `assets/<post-slug>/`.
4. Use `NN-<semantic-name>.png` filenames in article order.
5. If the filename exists, create a versioned sibling such as `03-trading-hours-v2.png`.
6. Record the final relative path in the JSON manifest.

Do not leave a final project image only in the generator's default output folder.

## 8. Visual QA

Review each asset against these categories:

| Category | Pass condition | Common failure |
|---|---|---|
| `context` | The image supports the nearby section | Generic finance image under a timing explanation |
| `factuality` | Times, objects, and relationships do not contradict the article | Wrong clock time or impossible process |
| `anatomy` | Faces, hands, posture, and devices look plausible | Extra fingers or fused objects |
| `text` | Required text is exact; otherwise no legible invented text | Broken Korean or fake labels |
| `brand` | No unauthorized logo or fabricated official UI | Fake brokerage or government interface |
| `style` | Palette, realism, and recurring subjects stay coherent | Random switch from documentary photo to cartoon |
| `crop` | Core subject remains clear on mobile | Key object placed at the extreme edge |

If one category fails, make at most one targeted regeneration that changes only the failed dimension. Do not make broad prompt changes that discard otherwise-correct composition. If the retry fails, mark the slot `failed` and report it rather than looping.

For UI instructions, official forms, branded products, or evidence images, use an actual user-provided or official source image. A generated conceptual UI may be used only when exact operation is not being taught, contains no copied branding, and is clearly described as illustrative.

## 9. Write alt text and captions

- Alt text should describe the information or situation a reader would miss, not start with “이미지” or repeat the filename.
- Captions should explain why the image matters to the adjacent paragraph.
- Keep factual details in the article body even when they also appear visually.
- When a photorealistic scene is illustrative rather than documentary, say so in the caption if confusion is plausible.

## 10. Compose the article

Create the JSON v1 manifest described in [`image-slot-manifest.md`](image-slot-manifest.md). Run the insertion CLI from the project root after every referenced file exists and has `approved` status.

```bash
python3.11 scripts/insert_article_images.py \
  --article drafts/post.md \
  --manifest drafts/image-manifest.json \
  --out drafts/post-with-images.md
```

The original article remains unchanged. Report the composed article path, all final image paths, and any unresolved slot.

## Decision examples

| Article | Appropriate plan | What to avoid |
|---|---|---|
| Travel or café review | Cover atmosphere photo, one location-orientation image, and only the details that support a real observation | A generated venue image presented as the author's visit evidence |
| Domestic-stock trading-hours guide | Everyday cover photo, verified timeline infographic, and a neutral checklist scene | Fake brokerage UI, invented prices, or profit imagery |
| Abstract opinion essay | One restrained concept illustration for the central metaphor and possibly one transition visual | Documentary-looking scenes that imply an event actually happened |
| App operation tutorial | User screenshot or official documentation image with callouts | A generated screen used as exact tap-by-tap instruction |

For repeatability, derive the slot plan from the same ordered questions: What changes here? What would a reader fail to picture? Which mode conveys that information with the least risk? If two candidate slots answer the same question, keep the stronger one.
