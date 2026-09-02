---
name: naver-blog-style
description: "Extract a reusable, topic-independent Naver Blog writing style through a choice-based interview, then apply the resulting style profile to drafts and revisions. Use when a user wants a personal blog tone, writing-style guide, or reusable Naver Blog style skill."
---

# Naver Blog Style

## Purpose

Build a personal writing-style profile that can be applied across topics. Separate the stable style layer from the variable topic layer:

- Stable: voice, reader distance, emotional temperature, sentence rhythm, paragraph density, structure, evidence posture, formatting, and forbidden patterns.
- Variable: subject matter, facts, keywords, examples, search intent, and call to action.

This skill is a style elicitation and application workflow. It is not a promise of search ranking and must not invent a fixed character-count, image-count, hashtag-count, or algorithm loophole.

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

## Naver-specific guardrails

Use Naver's official Search Advisor guidance as a quality reference: original experience and expertise, topic consistency, authentic and transparent writing, readable headings and paragraphs, concise and accurate titles, important information in text, and ongoing maintenance. Avoid keyword stuffing, copied or lightly rephrased material, misleading titles/thumbnails, and content that is mostly a link or advertisement.

Reference: https://searchadvisor.naver.com/guide/content-basic

