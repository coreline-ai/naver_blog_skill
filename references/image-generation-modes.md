# Image Generation Modes

Use this reference after an article has been finalized and visual slots have been selected.

## Mode decision table

| Mode | Use when | Avoid when |
|---|---|---|
| `photorealistic-natural` | A concrete person, place, product, daily activity, or time-of-day situation matters | The image could be mistaken for the author's evidence or a real event record |
| `infographic-diagram` | A timeline, process, comparison, checklist, system, or numeric relationship needs explanation | The facts are not verified or the graphic would rely on large amounts of generated text |
| `stylized-concept` | The section is abstract, reflective, emotional, or future-oriented | The reader needs documentary accuracy |
| `ui-mockup` | A generic interface concept helps explain a non-operational idea | Exact taps, official forms, transactions, or branded UI must be accurate |

Use an image-editing flow rather than these generate modes when the user supplied a target image and asked to preserve or change part of it.

## Shared visual brief

Define these values once per article and reuse them across prompts:

```text
Audience: <who reads the article>
Mood: <emotional temperature from the writing profile>
Palette: <primary, neutral, accent colors>
Rendering: <documentary photo, editorial illustration, clean diagram>
Continuity: <recurring person, place, season, time, materials>
Mobile priority: <subject size and safe crop>
Prohibited: <logos, fake UI, excessive text, evidence-like documents>
```

Change only what the section requires. Consistency matters more than making every image visually dramatic.

## `photorealistic-natural`

Use for lived situations such as commuting, cooking, visiting a place, using a product, or reviewing information after work.

Prompt for:

- an ordinary, plausible environment
- natural posture and restrained expression
- realistic hands, devices, reflections, and material texture
- lighting that matches the article's time and mood
- enough context to explain why the person is there
- negative space only when the asset needs title overlay

Avoid money piles, exaggerated celebration, staged pointing, generic corporate handshakes, impossible screens, and cinematic effects that conflict with an everyday blog voice.

If a scene is not the author's real photo, avoid captions that imply “제가 직접 찍은 사진입니다.” Use neutral wording or disclose that it aids understanding.

## `infographic-diagram`

Use for time ranges, ordered steps, comparison criteria, decision trees, and checklists.

Prefer:

- few large elements
- visual hierarchy that survives mobile scaling
- verified values supplied explicitly in the prompt
- icons, shape, and spacing rather than long labels
- article captions for detailed explanation

Generated text is error-prone. Keep labels short and exact. If factual labels are essential and deterministic accuracy matters, create the diagram in a code-native format rather than relying on raster generation.

## `stylized-concept`

Use when the article explains a viewpoint, change, emotion, or possibility that has no direct documentary scene.

Choose a clear visual metaphor tied to the section. Keep the metaphor simple enough that the caption can explain it in one sentence. Avoid famous living artists' exact styles, copyrighted characters, unrelated fantasy elements, and imagery that makes a factual claim.

## `ui-mockup`

Use only for a generic interface concept. It must not resemble a real brokerage, bank, government, medical, or commerce app closely enough to be mistaken for instructions.

Requirements:

- no real logos, product names, company names, or account information
- no actionable transaction details presented as real
- no invented official labels
- minimal or unreadable placeholder text unless exact text is required and verified
- caption that identifies the visual as conceptual when ambiguity remains

For operational tutorials, request a real screenshot or use an official source. Do not use a generated UI as evidence that a feature exists.

## Prompt scaffold

```text
Use case: <mode>
Asset type: <cover or inline blog image>
Section purpose: <what the image must help the reader understand or feel>
Scene/backdrop: <environment or information layout>
Subject: <main subject and concrete details>
Style/medium: <photo, editorial illustration, diagram, generic mockup>
Composition/framing: <landscape, subject placement, mobile crop>
Lighting/mood: <lighting and emotional temperature>
Color palette: <shared brief palette>
Text (verbatim): "<exact essential text only>"
Constraints: <truth, identity, branding, continuity, file-use constraints>
Avoid: <likely slot-specific defects>
```

Do not include `Text` when none is necessary.

## Slot-specific QA hints

### Cover

- The core situation is clear without reading small text.
- The subject is not hidden by a likely title crop.
- The image creates curiosity without promising a result the article cannot support.

### Inline explanation

- The visual answers the nearby section's question.
- It does not repeat the cover composition.
- Numbers or time cues match the final article.

### Checklist or conclusion

- The visual suggests review or completion without embedding the entire checklist.
- It leaves the actionable items in text for accessibility and accuracy.
