# Runtime traps (device-verified)

Lessons from shipping real iOS Shortcuts built outside the Shortcuts UI.
These are **not** theoretical — broken plists sign fine and still fail on device.

## 1. Media volume restore → 「알 수 없는 동작」

**Bad pattern**

```
get_volume → set_variable(PrevVol) → set_volume(1.0) → … → set_volume(var:PrevVol)
```

Serializing `WFVolume` as a **named Variable** text-token attachment often makes the Set Volume step show as:

- 알 수 없는 동작  
- 이 버전의 단축어에 앱에서 이 동작을 찾을 수 없습니다  
- 이 동작의 각 매개변수에 대한 값을 선택하십시오  

**Do instead**

- Use a **literal** float only: `set_volume` with `volume: 1.0` (or skip volume entirely).  
- TTS + notification do not need volume save/restore for unattended flows.

`validate_recipe` warns on variable-name / magic-attachment volume and on the restore loop sequence.

## 2. Conditional `WFInput` Variable → unbound If

**Bad pattern**

```json
{
  "type": "conditional_start",
  "params": {
    "condition": "contains",
    "value": "OK",
    "var_name": "OCR텍스트"
  }
}
```

when compiled as **If with `WFInput = {Type: Variable}`** (no Get Variable step).

**Do instead (golden)**

```
ocr_extract_text   # previous action output = text on magic stack
conditional_start  # contains "OK" — no WFInput, no var_name
```

If you must use a named variable, this MCP expands `var_name` to:

```
get_variable(OCR텍스트) → conditional_start (no WFInput on If)
```

## 3. Screenshot then stuck 「이미지」 popup

If `take_screenshot` is not immediately followed by an **image consumer** (`ocr_extract_text`, crop, resize, …), or the next step is broken/unbound, iOS presents a content sheet titled **이미지** that needs **취소/완료**.

**Do instead**

```
take_screenshot
ocr_extract_text    # adjacent
conditional_start   # on OCR text
```

Do not invent non-standard `WFInput` keys on extract/setvariable unless reverse-engineered from a trusted export.

## 4. Crop

| Identifier | macOS | iOS | Notes |
|------------|-------|-----|-------|
| `is.workflow.actions.cropimage` | often **missing action** | usually present | bare crop → interactive UI |
| `is.workflow.actions.image.crop` | present (curated default) | present | still needs sensible size/position |

For full-screen OCR (find button labels), **skip crop**.

## 5. Vibrate

`is.workflow.actions.vibrate` is often **iOS-only**. Omit on macOS / dual-target builds.

## 6. Open app (platform)

Opening a phone-only app on **Mac** prompts “choose an app” if it is not installed. Target `ios` for phone-only apps; use `target_platform` preflight.

## 7. Import / delete limits

- `shortcuts` CLI: list / run / view / sign only — **no** import or delete.  
- Auto-import via `open` may still need one GUI confirm.  
- Scripted delete is unreliable; folder move (`zz_삭제예정`) + manual purge works better.  
- Never bulk-import probe shortcuts into a personal library.

## Preferred screenshot OCR recipe

Template: `screenshot_ocr_contains` (`list_templates`).

```
open_app → delay → take_screenshot → ocr_extract_text
→ if contains "OK" → speak + notify
→ else → speak + notify
```

No crop, no volume restore, no vibrate.

## Related

- Magic stack / `$ref`: [MAGIC_VARIABLES.md](./MAGIC_VARIABLES.md)  
- Coverage honesty: [ACTION_COVERAGE.md](./ACTION_COVERAGE.md)  
- Agent workflow: [../AGENTS.md](../AGENTS.md)
