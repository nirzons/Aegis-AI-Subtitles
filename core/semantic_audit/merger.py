import os
import shutil
from tkinter import messagebox
from core.text_processing import fix_rtl, force_split_overlong_line
from utils.settings import SETTINGS
from utils.app_utils import log

def merge_approved_suggestions(app, approved_indices, result, translated_path):
    """
    Phase 2, Step 2.3: Merges the user-approved senior editor fixes 
    back into the actual translated SRT file on disk.
    """
    profile = SETTINGS.get_active_profile()
    is_rtl = profile.target_is_rtl if profile else False
    
    if not approved_indices:
        messagebox.showinfo("No Changes", "No changes were applied as no items were approved.", parent=app.root)
        return
        
    try:
        # 1. Create indestructible safety backup with state-protection check
        backup_path = translated_path + ".bak"
        backup_written = False
        
        if os.path.exists(backup_path):
            ans = messagebox.askyesnocancel(
                "Backup File Exists",
                f"A backup version for this subtitle already exists:\n{os.path.basename(backup_path)}\n\n"
                f"• Click [Yes] to OVERWRITE it with a fresh copy of the active file.\n"
                f"• Click [No] to KEEP the existing backup and proceed with merging.\n"
                f"• Click [Cancel] to abort the merging operation completely.",
                parent=app.root
            )
            if ans is None: # User pressed Cancel
                return
            elif ans is True: # User pressed Yes (Overwrite)
                shutil.copy2(translated_path, backup_path)
                backup_written = True
            else: # User pressed No (Keep Old)
                pass
        else:
            # Quietly write initial backup if none exists
            shutil.copy2(translated_path, backup_path)
            backup_written = True
        
        # 2. Build fast mapping lookup for approved indices
        suggestions_map = {
            str(sug.get("index")): sug.get("replacement_he", "") 
            for sug in result.get("suggestions", []) 
            if str(sug.get("index")) in approved_indices
        }
        
        # 3. Parse the original file block-by-block
        with open(translated_path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
        
        # Standardize linebreaks to match and split blocks securely
        content = raw.replace("\r\n", "\n")
        blocks = [b.strip() for b in content.split('\n\n') if b.strip()]
        new_blocks = []
        merge_count = 0
        
        for b in blocks:
            lines = b.split('\n')
            if len(lines) >= 3:
                cue_idx = lines[0].strip()
                if cue_idx in suggestions_map:
                    # OVERWRITE target lines (Line 2+), preserving Cue & Timestamp
                    new_text = suggestions_map[cue_idx]
                    
                    # Safety Catch: Apply deterministic mid-point split if text exceeds standard constraints without manual breaks
                    if "\n" not in new_text and "<br>" not in new_text:
                        new_text = force_split_overlong_line(new_text)
                        
                    # Re-apply OS/media-player specific RTL punctuation formatting!
                    if is_rtl:
                        new_text = fix_rtl(new_text, is_rtl=True, profile=profile)
                        
                    new_block = f"{cue_idx}\n{lines[1]}\n{new_text}"
                    new_blocks.append(new_block)
                    merge_count += 1
                    continue
            new_blocks.append(b)
            
        # 4. Ensure clean, pure \n across all blocks, then let Python handle OS native translation
        final_content = "\n\n".join(new_blocks) + "\n"
        # Strip existing \r to prevent double \r\r\n on Windows when written in text-mode
        final_content = final_content.replace("\r\n", "\n").replace("\r", "")
        
        with open(translated_path, "w", encoding="utf-8-sig") as f:
            f.write(final_content)
            
        # 5. Log and Display visual success summary!
        log_msg = f"💾 [Merger] Merged {merge_count} Senior Editor fixes into {os.path.basename(translated_path)}!"
        log(app.log_queue, app.session_log_file, log_msg)
        
        if backup_written:
            log(app.log_queue, app.session_log_file, f"🛡️ [Merger] Safety backup updated at {os.path.basename(backup_path)}.")
            backup_status_msg = f"• Backup written securely as:\n  {os.path.basename(backup_path)}"
        else:
            log(app.log_queue, app.session_log_file, f"🛡️ [Merger] Previous safety backup preserved intact.")
            backup_status_msg = f"• Previous backup preserved securely on disk."
            
        messagebox.showinfo("Merge Successful", 
            f"🎉 Merging Completed Successfully!\n\n"
            f"• {merge_count} approved edits physically applied.\n"
            f"{backup_status_msg}\n\n"
            f"Your finalized SRT file is updated and ready for viewing!", parent=app.root)
            
    except Exception as e:
        messagebox.showerror("Merging Failure", f"Failed to rewrite the SRT file:\n\n{e}", parent=app.root)
