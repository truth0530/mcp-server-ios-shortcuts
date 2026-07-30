# Action reference

High-level recipe types accepted by `build_shortcut` / `validate_recipe`.

Agents should prefer calling the live `list_actions` tool (always up to date with the running server). This document mirrors the v2 catalog for offline reading.

## Recipe shape

```json
{ "type": "<action_type>", "params": { } }
```

Escape hatches:

- `"type": "is.workflow.actions.someaction"` with raw params  
- `"type": "open_app", "wf_params": { ... }` — full WF parameter object  

## Control flow

| type | params | notes |
|------|--------|--------|
| `conditional_start` | `group_id`, `condition`, `value` / `number` | conditions: equals, contains, greater_than, … |
| `conditional_else` | `group_id` | |
| `conditional_end` | `group_id` | |
| `repeat_start` | `group_id`, `count` | |
| `repeat_end` | `group_id` | |
| `repeat_each_start` | `group_id` | |
| `repeat_each_end` | `group_id` | |
| `menu_start` | `group_id`, `prompt`, `items[]` | |
| `menu_item` | `group_id`, `title` | |
| `menu_end` | `group_id` | |

**Always share one UUID `group_id` across a single if/repeat/menu block.**

```json
[
  { "type": "text", "params": { "text": "hello world" } },
  {
    "type": "conditional_start",
    "params": {
      "group_id": "11111111-2222-3333-4444-555555555555",
      "condition": "contains",
      "value": "hello"
    }
  },
  { "type": "show_notification", "params": { "title": "Yes", "body": "matched" } },
  {
    "type": "conditional_else",
    "params": { "group_id": "11111111-2222-3333-4444-555555555555" }
  },
  { "type": "show_notification", "params": { "title": "No", "body": "no match" } },
  {
    "type": "conditional_end",
    "params": { "group_id": "11111111-2222-3333-4444-555555555555" }
  }
]
```

## Interaction

| type | key params |
|------|------------|
| `delay` | `seconds` |
| `ask` | `prompt`, `default`, `input_type` |
| `show_result` | `text` (empty = show stack) |
| `show_alert` | `title`, `message`, `show_cancel` |
| `show_notification` | `title`, `body`, `sound` |
| `speak_text` | `text`, `wait`, `rate`, `language` |
| `vibrate` | — |
| `play_sound` | — |
| `comment` | `text` |
| `choose_from_list` | (generic / `wf_params`) |
| `exit_shortcut` | — |
| `stop_and_output` | — |
| `wait_to_return` | — |
| `nothing` | — |

## Apps / system

| type | key params |
|------|------------|
| `open_app` | `bundle_id`, `app_name` |
| `open_url` | `url` |
| `search_web` | `query`, `destination` |
| `run_shortcut` | `name`, `show_while_running` |
| `set_volume` / `get_volume` | `volume` 0.0–1.0 or variable name |
| `set_brightness` | `brightness` 0.0–1.0 |
| `set_flashlight` | `setting` On/Off/Toggle |
| `set_low_power_mode` | `on` |
| `set_focus` | `mode`, `until` |
| `get_battery` | — |
| `get_device_details` | `detail` |
| `get_network_details` | `detail` |
| `set_wifi` / `set_bluetooth` / `set_airplane_mode` / `set_cellular` | `on` |
| `lock_screen` | — |

## Text / clipboard / data

| type | key params |
|------|------------|
| `text` | `text` |
| `get_clipboard` / `set_clipboard` | `text` optional for set |
| `change_case` | `case` |
| `replace_text` | `find`, `replace`, `case_sensitive`, `regular_expression` |
| `split_text` / `combine_text` | `separator`, `custom` |
| `match_text` | `pattern`, `case_sensitive` |
| `count` | `count_type` |
| `calculate` | `operation`, `operand` |
| `base64_encode` | `mode` Encode/Decode |
| `url_encode` | `mode` |
| `hash` | `type` MD5/SHA… |
| `set_variable` / `get_variable` / `add_to_variable` | `var_name` |
| `list` | `items[]` |
| `dictionary` | `items{}` |
| `get_dictionary_value` / `set_dictionary_value` | `key`, `value` |
| `get_item_from_list` | `specifier`, `index` |

## Media / files / network

| type | key params |
|------|------------|
| `take_screenshot` | — |
| `take_photo` | `count`, `camera` |
| `select_photos` | `multiple` |
| `crop_image` | `position` |
| `resize_image` | `width`, `height` |
| `ocr_extract_text` | — |
| `make_pdf` | — |
| `save_file` | `ask_where`, `overwrite` |
| `create_folder` | `path` / `name` |
| `rename_file` | `name` |
| `get_contents_of_url` | `url`, `method`, `headers`, `body`, `body_type` |
| `get_headers_of_url` | `url` |

## Communication

| type | key params |
|------|------------|
| `send_message` | `recipients[]`, `message`, `show_compose` (default true) |
| `send_email` | `to[]`, `subject`, `body`, `show_compose` |
| `share` | — |
| `airdrop` | — |

## macOS scripting

| type | key params |
|------|------------|
| `run_shell_script` | `script`, `shell`, `input_mode` |
| `run_applescript` | `script` |

## Icon colors (`icon_color` on build)

`red` `orange` `yellow` `green` `teal` `blue` `indigo` `purple` `pink` `gray` `dark_gray` `taupe`

## Version notes

Workflow action identifiers and parameter keys can differ slightly across iOS/macOS releases. If a built shortcut opens but an action shows as broken in the editor, inspect with `inspect_shortcut` on the raw file and adjust via `wf_params` or a full `is.workflow.actions.*` type.
