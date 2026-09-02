# Image Slot Manifest v1

The manifest connects explicit article markers to approved local image files. It is JSON so validation and insertion require only the Python standard library.

## Article marker

```md
<!-- naver-image:cover -->
```

Rules:

- ID pattern: lowercase ASCII letters, digits, and hyphens
- Each ID appears exactly once in the article
- Each article marker has exactly one manifest record
- Do not place markers inside fenced code blocks

## Top-level object

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `version` | integer | yes | Must be `1` |
| `asset_root` | string | yes | Project-relative directory containing all referenced images |
| `slots` | array | yes | Slot records in article order |

The insertion CLI resolves paths from the current working directory. Run it from the project root. `asset_root` and every slot path must be relative, stay inside the project root, and must not contain `..`.

## Slot record

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `id` | string | yes | Unique marker ID |
| `role` | string | yes | `cover` or `inline` |
| `placement` | string | yes | Human-readable location and reason |
| `purpose` | string | yes | Information or emotional job of the image |
| `mode` | string | yes | Generation mode used for the slot |
| `prompt` | string | yes | Final generation or edit prompt |
| `alt` | string | yes | Accessible image description |
| `caption` | string | yes | Caption text; may be empty |
| `path` | string | yes | Project-relative final image path under `asset_root` |
| `status` | string | yes | Must be `approved` before composition |

## Valid example

```json
{
  "version": 1,
  "asset_root": "assets/domestic-stock-trading",
  "slots": [
    {
      "id": "cover",
      "role": "cover",
      "placement": "H1 제목 바로 아래",
      "purpose": "퇴근 후에도 국내 주식을 확인할 수 있다는 핵심 상황을 제시",
      "mode": "photorealistic-natural",
      "prompt": "퇴근 후 집에서 스마트폰으로 일반적인 주식 차트를 확인하는 직장인의 자연스러운 편집 사진",
      "alt": "퇴근 후 거실에서 스마트폰으로 주식 정보를 확인하는 직장인",
      "caption": "이해를 돕기 위한 이미지입니다.",
      "path": "assets/domestic-stock-trading/01-cover.png",
      "status": "approved"
    },
    {
      "id": "trading-hours",
      "role": "inline",
      "placement": "거래시간 설명 문단 뒤",
      "purpose": "프리·메인·애프터마켓의 시간 흐름을 단순화",
      "mode": "infographic-diagram",
      "prompt": "오전부터 저녁까지 이어지는 세 구간의 흐름을 보여주는 글자 없는 미니멀 타임라인",
      "alt": "하루 주식 거래시간이 세 구간으로 이어지는 타임라인",
      "caption": "세부 거래시간은 본문과 거래소의 최신 안내를 함께 확인해야 합니다.",
      "path": "assets/domestic-stock-trading/02-trading-hours.png",
      "status": "approved"
    }
  ]
}
```

## Composition result

The marker:

```md
<!-- naver-image:trading-hours -->
```

becomes:

```md
![하루 주식 거래시간이 세 구간으로 이어지는 타임라인](<assets/domestic-stock-trading/02-trading-hours.png>)

*세부 거래시간은 본문과 거래소의 최신 안내를 함께 확인해야 합니다.*
```

## Validation failures

Composition must stop without modifying the original when:

- JSON is malformed or `version` is unsupported
- `asset_root` is absolute or escapes the current project
- IDs are empty, invalid, or duplicated
- marker IDs and manifest IDs do not match exactly
- a slot is not `approved`
- an image path is missing, absolute, outside `asset_root`, outside the project, or does not exist
- the output exists and `--force` was not supplied

Keep failed or planned slots out of the composition manifest until they are approved. Report them separately to the user.
