---
name: naver-blog-style
description: "네이버 블로그 주제로 원고를 작성·수정하고 기존 블로그 본문 참고와 개인 문체를 적용한다. 네이버 블로그 스킬, 기존 글 N개 참고, 주제와 함께 정보 슬라이드·카드뉴스형 N장으로 완성해줘, 이미지 포함 블로그 글 요청에 사용한다. 이미지가 명시된 완성 요청은 실제 생성·검수·본문 삽입까지 연결하고, 프롬프트만 요청하면 계획에서 끝낸다. 단일 글과 문체 요청을 담당하며 공개 발행을 수행하지 않는다."
---

# Naver Blog Style

## Purpose

Build a personal writing-style profile that can be applied across topics. Separate the stable style layer from the variable topic layer:

- Stable: voice, reader distance, emotional temperature, sentence rhythm, paragraph density, structure, evidence posture, formatting, and forbidden patterns.
- Variable: subject matter, facts, keywords, examples, search intent, and call to action.

This skill supports topic-based article creation and reusable style elicitation/application, with visual composition for explicit image requests. A requested production count and the image-inclusive single-article default of five are completion requirements, not SEO formulas. Do not invent ranking rules, fixed keyword/hashtag formulas, or algorithm loopholes.

## Guided option requests

When the user explicitly invokes `$naver-blog-wizard` or asks to choose article/image options one question at a time, read [the guided workflow](skills/naver-blog-wizard/SKILL.md) before the topic completion route. Reuse supplied options and wait for each unresolved answer. This route handles a single article and its images; it does not start a personal style interview, a series, or Naver UI actions. Ordinary topic completion requests retain the existing route below.

## Topic-based requests

For a Naver Blog topic request, write the article using the existing `docs/naver-blog-style-profile.md` when available. Do not start a new style interview unless the user asks to define their style. For a single article with a requested image type/count and “완성해줘”, “작성해줘”, or “만들어줘”, read [the topic-to-image completion workflow](references/topic-image-completion-workflow.md) and carry the task through actual generation, visual QA, and insertion. Prepare internal article/request files yourself; do not require the user to supply an article or slot JSON before starting from their topic. Series requests use the existing series workflow.

New or rewritten articles follow [title selection](#selecting-a-post-title) after the body draft is grounded in facts. A title-only request uses [naver-title](skills/naver-title/SKILL.md) and stops at the requested title results. An existing article's image-only request preserves its title and body.

Before drafting new information, how-to, or comparison articles, read [blog research](references/blog-research-workflow.md). Default to section-blog and five existing post bodies; honor an explicit search source, reference count (1–8), or opt-out. Rewrites use this research only when search supplementation is requested; personal-experience reviews, diaries, and style interviews use it only when explicitly requested. Title-only and image-only requests skip body research. Reference count is separate from image count and title candidates.

Use actual observed post bodies, a validated research context, and a separate analysis brief to identify reader intent, common coverage, gaps, and claims needing official verification. Keep the existing voice and write an original draft; repeated blog mentions do not establish purchase share, popularity rankings, or the author's experience. Report actual reference count and collection limits. An explicit N-body requirement is unmet until N unique valid bodies are available; a default-count partial result may support writing with its scope disclosed. Then follow the existing title and visual completion stages.

## Choice-first interview protocol

When the user is still defining their style:

1. Ask one question per turn. Ask two only when they measure the same dimension and can be answered together.
2. Present 3–5 clearly different choices labelled A, B, C, D, or E. Each choice must describe the writing behavior it produces, not merely name an adjective.
3. Let the user answer with one choice, multiple choices such as `A+C`, a strength such as `B 강하게`, or a custom answer such as `D에 가깝지만 더 담백하게`.
4. Do not frame one option as the correct or algorithmically superior answer. The goal is fit, not optimization theater.
5. After every 4–6 questions, summarize the provisional profile in plain language and identify only the next unresolved contrast.
6. Keep a state table with `dimension`, `choice`, `strength`, `confidence`, and `evidence`. Do not treat a vague preference as a hard rule until it is confirmed by an example or a later answer.
7. If answers conflict, show the conflict and ask a contrast question instead of silently averaging it.
8. Ask for short user-written samples only after the preference questions establish a direction. Use them to calibrate rhythm and wording, not to replace the user's stated intent.

Use the question bank in [`references/choice-question-bank.md`](references/choice-question-bank.md). Do not ask every question mechanically; route to the smallest set that resolves uncertainty. For a complete profile, cover all seven dimensions at least once.

## Interview phases

Route through these phases in order unless the user asks to skip one:

1. Author identity and reader relationship
2. Tone, emotional temperature, and humor
3. Sentence endings, vocabulary, and rhythm
4. Paragraphs, headings, and article flow
5. Evidence, opinions, criticism, and uncertainty
6. Visual formatting, titles, links, and calls to action
7. Boundaries, disliked patterns, and sample-based calibration

At the beginning of each phase, state its purpose in one short sentence. Show progress as `1/7`, `2/7`, and so on, but do not make the interview feel like a form.

## Style extraction rules

Convert answers into behavioral rules, not adjective piles. For example:

- Weak: “친근하고 전문적으로 쓴다.”
- Useful: “첫 문단에서 결론을 평이하게 말하고, 이후 직접 해본 과정과 근거를 짧은 소제목 아래 나눈다. 전문용어는 처음 한 번만 풀어쓴다.”

For each extracted rule, classify it as:

- `always`: stable preference confirmed by repeated answers or sample evidence
- `usually`: preferred default with context exceptions
- `optional`: a flavor to use sparingly
- `avoid`: explicit dislike or a clear contradiction

Do not force every article into one rigid outline. Produce a core style plus deliverable adapters for review, guide, diary, announcement, comparison, and promotional-link posts when those modes are relevant.

## Final profile output

When the interview is complete, present a concise profile before drafting anything:

1. Style identity in one sentence
2. Author persona and reader distance
3. Tone and emotional range
4. Sentence and paragraph rhythm
5. Preferred article flow
6. Evidence and opinion behavior
7. Formatting and title behavior
8. `always / usually / optional / avoid` rules
9. Three short before/after examples using neutral placeholder topics
10. A pre-publication checklist

Ask for confirmation only on contradictions or high-impact preferences. If the user asks to make it a reusable skill, write the confirmed profile to `docs/naver-blog-style-profile.md` and keep this skill's workflow separate from the personalized profile. Do not overwrite a prior profile without showing the proposed changes.

## Applying the profile

Before writing a post:

- Identify the deliverable mode and search intent, but do not let either change the core voice without permission.
- Draft using the confirmed `always` and `usually` rules.
- Use only the amount of formatting needed for mobile readability.
- Keep the title accurate and specific to the page.
- Make the opening answer the reader's immediate question or establish the author's concrete situation.
- Keep facts, personal observations, and recommendations distinguishable.
- Use original experience, screenshots, examples, or sources where appropriate.
- End with a useful summary or natural next step; do not manufacture urgency.

## Selecting a post title

Use the existing [naver-title skill](skills/naver-title/SKILL.md) with the factual body draft, sources, subject, search intent, reader situation, concrete benefit, unconfirmed claims, voice, and explicit title constraints. Its framework and evaluation rubric own candidate creation and selection.

- For integrated writing with no title type specified, explicitly request three search titles, three home-feed titles, and three hybrid titles for internal comparison, then select one hybrid title. Honor an explicit type or candidate count. A fixed title bypasses automatic optimization. Standalone naver-title calls retain their own defaults and output formats.
- Make the reason to read specific to the body. A question is one possible structure, not the default for every post. Verify a title's numbers against its actual list or evidence, rather than the image count. Revise or discard an unsupported promise without inventing facts to support it.
- Keep candidates, evidence, and the selection reason in separate editorial notes. Use the selected title in the article; show the full candidate set only when requested. Do not add a default approval question for each internal candidate. Let the opening deliver or clearly introduce the information promised by the title.
- Finalize the H1 and body before selecting image slots or computing article hashes and image prompts. The title strategy and the image presentation are separate: “혼합형 5장” refers to mixed images, not five title candidates. Do not add title-strategy fields to the image request or manifest.
- If a title changes after visual planning, preserve prior files and recompute the source hash and full prompts in a new version. Recheck image wording/context and composition before reuse; an earlier approval does not establish that assets match the revised article. Preserve the existing article/slide text limits rather than truncating the H1 to fit a cover.

## Optional visual-composition mode

Enter this mode when the user explicitly asks for a representative image, cover/section images, an image-inclusive draft, or “정보 슬라이드 / 카드뉴스형 N장으로 네이버 블로그 글을 완성”. A writing-only request remains text-only. An explicit restriction such as “프롬프트만” or “이미지 생성은 하지 마” limits the task to planning even if it also mentions a complete article.

Route explicit visual requests into the smallest matching mode:

- `plan-only`: The user asks for image positions, concepts, prompts, or a storyboard but not generated files.
- `generate-and-compose`: The user asks to create and place images, including a topic plus an image type/count and a request to complete the post. Honor N exactly; for an image-inclusive single post with no count, use five including the cover. All `info-slide` images, including the cover, remain slides. Only explicit `mixed` makes the cover standard. Continue from prompt preparation to the current image tool without reconfirming the already-requested scope.
- `edit-existing`: The user asks to alter supplied or previously generated images; use an image-editing flow rather than generating unrelated replacements.

Finalize and fact-check the article before visual planning. Then read [`references/visual-composition-workflow.md`](references/visual-composition-workflow.md). Read [`references/image-generation-modes.md`](references/image-generation-modes.md) when choosing between photography, illustration, infographic, or UI-like visuals. Read [`references/image-slot-manifest.md`](references/image-slot-manifest.md) before creating a manifest or inserting files.

For reusable slot selection, article-grounded slide wording, or assembled per-image prompts, read [the image prompt contract](references/blog-image-prompt-contract.md) and use `scripts/build_blog_image_prompts.py`. Give it the finalized article and the explicit visual slots already selected for this request. Preserve their IDs, order, roles, and scene choices. Fallback entries are candidates requiring contextual review, not finished art direction. `plan-only` returns plans and prompts; `generate-and-compose` passes them to the current image tool, then follows visual QA and the existing manifest. `edit-existing` uses a verified original reference and the current tool's actual editing flow. The helper never generates, attaches, approves, or uploads an image itself.

Use `--operation generate-and-compose` for a completion request. If the plan returns `design_slots`, design the requested N distinct contextual slots and retry; do not lower N to the source heading cap or pad with generic pictures. `generate_images` is the next agent action, not evidence that images already exist. After QA and composition, use the paired manifest/composed-article verification in the contract before reporting the finished post.

### Visual routing and boundaries

- Give each requested image a distinct informational or emotional role. Honor the explicit production count or the applicable completion default without treating it as an SEO formula or automatically illustrating every heading.
- Choose the visual medium, scene, composition, and mood from the article title, adjacent section, concrete situation, and explanatory purpose. A writing profile is a tone input, not a reusable image template. Follow [contextual image direction](skills/naver-series-workflow/references/contextual-image-direction.md) for new or replacement visuals.
- For multiple articles, reset the visual brief per article and compare the set before generation and after QA. Changing only the topic label, background, or palette does not resolve a repeated layout. Deliberate series identity is allowed; unrelated topics must not inherit it by accident.
- Let the confirmed writing profile influence visual temperature, palette, reader distance, and humor without modifying the profile file.
- Prefer actual user screenshots or official source material when exact UI, forms, policies, or instructions matter. Do not fabricate a branded interface, official document, evidence photo, or experience record.
- Keep important information in article text. Images may support the explanation but must not become the only carrier of facts.
- Avoid in-image Korean text unless it is essential or the user explicitly requests an information slide. An explicit `info-slide` uses article-grounded Korean title/key points with a 4:5, recommended 1080×1350 brief; `mixed` uses a standard cover and information slides inline. Inspect the actual wording, ratio, and readability before approval. General images retain the contextual medium and composition; these presentation choices do not redefine manifest modes.
- Treat photorealistic generated scenes as illustrative. If a reader could mistake one for the author's evidence or experience, label it as an image created to aid understanding.

### Output contract

For `generate-and-compose`, produce and report:

1. The final fact-checked article with explicit image-slot markers
2. A JSON v1 image manifest containing purpose, placement, mode, prompt, alt text, caption, path, and approval status
3. Final local image files under `assets/<post-slug>/`
4. A separate Markdown article with approved images inserted
5. A short failure report for any unresolved slot

An N-image post is complete only with N approved, unique local image files and all N inserted into the final article, with the requested presentation retained. Prompts, planned flags, a save path, or an unchecked manifest do not satisfy this. Report the final article and images with actual generation/visual-QA evidence; local `package_verified` covers file/composition checks only.

Use filenames shaped like `NN-<semantic-name>.png`. Never overwrite an existing image or article unless the user explicitly requests replacement; create a versioned sibling instead. Project-bound generated images must be copied into the workspace rather than left only in the generator's default output directory.

If generation or visual QA fails, retry at most once per slot with one targeted correction. If it still fails, preserve useful work and report partial preparation with the unresolved slot; never label it as the requested N-image completion. If a required source image is missing, ask for that image instead of inventing it.

## Naver-specific guardrails

Use Naver's official Search Advisor guidance as a quality reference: original experience and expertise, topic consistency, authentic and transparent writing, readable headings and paragraphs, concise and accurate titles, important information in text, and ongoing maintenance. Avoid keyword stuffing, copied or lightly rephrased material, misleading titles/thumbnails, and content that is mostly a link or advertisement.

Reference: https://searchadvisor.naver.com/guide/content-basic
