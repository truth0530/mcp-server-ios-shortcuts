#!/usr/bin/env python3
"""
iOS Shortcuts Plist Generator Engine
Converts high-level JSON action recipes into Apple Binary Plist (.shortcut) files.
"""

import os
import uuid
import plistlib
import subprocess

ACTION_MAPPINGS = {
    "date": "is.workflow.actions.date",
    "conditional": "is.workflow.actions.conditional",
    "get_location": "is.workflow.actions.getcurrentlocation",
    "delay": "is.workflow.actions.delay",
    "open_app": "is.workflow.actions.openapp",
    "take_screenshot": "is.workflow.actions.takescreenshot",
    "crop_image": "is.workflow.actions.cropimage",
    "ocr_extract_text": "is.workflow.actions.extracttextfromimage",
    "set_variable": "is.workflow.actions.setvariable",
    "get_volume": "is.workflow.actions.getvolume",
    "set_volume": "is.workflow.actions.setvolume",
    "speak_text": "is.workflow.actions.speaktext",
    "show_notification": "is.workflow.actions.notification",
    "vibrate": "is.workflow.actions.vibrate"
}

def create_action(action_type: str, params: dict) -> dict:
    identifier = ACTION_MAPPINGS.get(action_type, action_type)
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": params
    }

def build_shortcut_plist(actions_config: list, name: str, output_dir: str = "./dist") -> str:
    os.makedirs(output_dir, exist_ok=True)
    raw_path = os.path.join(output_dir, f"{name}_raw.shortcut")
    signed_path = os.path.join(output_dir, f"{name}.shortcut")

    wf_actions = []
    
    # Process actions recipe
    for item in actions_config:
        atype = item.get("type")
        args = item.get("params", {})

        if atype == "date":
            wf_actions.append(create_action("date", {"WFDateActionDateTemplate": args.get("date_template", "Current Date")}))
        
        elif atype == "conditional_start":
            cond_enum = 99 if args.get("condition") == "contains" else 4
            wf_actions.append(create_action("conditional", {
                "GroupingIdentifier": args["group_id"],
                "WFControlFlowMode": 0,
                "WFCondition": cond_enum,
                "WFConditionalActionString": args.get("value", "")
            }))
        
        elif atype == "conditional_else":
            wf_actions.append(create_action("conditional", {
                "GroupingIdentifier": args["group_id"],
                "WFControlFlowMode": 1
            }))
            
        elif atype == "conditional_end":
            wf_actions.append(create_action("conditional", {
                "GroupingIdentifier": args["group_id"],
                "WFControlFlowMode": 2
            }))
            
        elif atype == "get_location":
            wf_actions.append(create_action("get_location", {}))
            
        elif atype == "delay":
            wf_actions.append(create_action("delay", {"WFDelayTime": args.get("seconds", 1)}))
            
        elif atype == "open_app":
            bundle_id = args.get("bundle_id", "com.shiftee.app")
            app_name = args.get("app_name", "시프티")
            wf_actions.append(create_action("open_app", {
                "WFAppIdentifier": bundle_id,
                "WFSelectedApp": {"BundleIdentifier": bundle_id, "Name": app_name}
            }))
            
        elif atype == "take_screenshot":
            wf_actions.append(create_action("take_screenshot", {}))
            
        elif atype == "crop_image":
            wf_actions.append(create_action("crop_image", {"WFCropImagePosition": args.get("position", "Custom")}))
            
        elif atype == "ocr_extract_text":
            wf_actions.append(create_action("ocr_extract_text", {}))
            
        elif atype == "set_variable":
            wf_actions.append(create_action("set_variable", {"WFVariableName": args.get("var_name")}))
            
        elif atype == "get_volume":
            wf_actions.append(create_action("get_volume", {}))
            
        elif atype == "set_volume":
            vol = args.get("volume", 1.0)
            if isinstance(vol, str):  # variable reference
                wf_actions.append(create_action("set_volume", {
                    "WFVolume": {
                        "Value": {"VariableName": vol, "Type": "Variable"},
                        "WFSerializationType": "WFTextTokenAttachment"
                    }
                }))
            else:
                wf_actions.append(create_action("set_volume", {"WFVolume": float(vol)}))
                
        elif atype == "speak_text":
            wf_actions.append(create_action("speak_text", {
                "WFSpeakTextText": args.get("text", ""),
                "WFSpeakTextWait": args.get("wait", True),
                "WFSpeakTextRate": args.get("rate", 0.45)
            }))
            
        elif atype == "show_notification":
            wf_actions.append(create_action("show_notification", {
                "WFNotificationActionTitle": args.get("title", ""),
                "WFNotificationActionBody": args.get("body", "")
            }))
            
        elif atype == "vibrate":
            wf_actions.append(create_action("vibrate", {}))

        else:
            # Generic action fallback
            wf_actions.append(create_action(atype, args))

    shortcut_dict = {
        "WFWorkflowClientVersion": "2600.0.1",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 59793,
            "WFWorkflowIconStartColor": 4282601983
        },
        "WFWorkflowInputContentItemClasses": [
            "WFAppStoreAppContentItem", "WFArticleContentItem", "WFContactContentItem",
            "WFDateContentItem", "WFEmailAddressContentItem", "WFFolderContentItem",
            "WFGenericFileContentItem", "WFImageContentItem", "WFiTunesProductContentItem",
            "WFLocationContentItem", "DCMapsLinkContentItem", "AVAssetContentItem",
            "PDFContentItem", "PHAssetContentItem", "WFPBRichTextContentItem",
            "WFSafariWebPageContentItem", "WFStringContentItem", "WFURLContentItem"
        ],
        "WFWorkflowActions": wf_actions,
        "WFWorkflowTypes": ["NCWidget", "WatchKit"]
    }

    with open(raw_path, "wb") as f:
        plistlib.dump(shortcut_dict, f, fmt=plistlib.FMT_BINARY)

    # Attempt signing automatically via macOS shortcuts sign CLI
    try:
        res = subprocess.run(
            ["shortcuts", "sign", "-m", "anyone", "-i", raw_path, "-o", signed_path],
            capture_output=True, text=True
        )
        if res.returncode == 0:
            return os.path.abspath(signed_path)
    except Exception:
        pass
    
    return os.path.abspath(raw_path)
