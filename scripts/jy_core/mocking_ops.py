import os
import json
import uuid
import shutil
import pyJianYingDraft as draft

class MockVideoMaterial(draft.VideoMaterial):
    def __init__(self, material_id, duration, name, path):
        self.material_id = material_id
        self.duration = duration
        self.material_name = name
        self.path = path
    def serialize(self):
        return {
            "id": self.material_id, "type": "video", "name": self.material_name, "path": self.path,
            "duration": self.duration, "material_id": self.material_id
        }

class MockAudioMaterial(draft.AudioMaterial):
    def __init__(self, material_id, duration, name, path):
        self.material_id = material_id
        self.duration = duration
        self.material_name = name
        self.path = path
    def serialize(self):
        return {
            "id": self.material_id, "type": "audio", "name": self.material_name, "path": self.path,
            "duration": self.duration, "material_id": self.material_id
        }

class CompoundSegment:
    def __init__(self, material_id, target_timerange):
        self.material_id = material_id
        self.target_timerange = target_timerange
    def serialize(self):
        return {
             "id": str(uuid.uuid4()).upper(), "material_id": self.material_id,
             "target_timerange": self.target_timerange.serialize(),
             "render_index": 0, "type": "video"
        }

class MockingOpsMixin:
    """
    JyProject 的协议补丁与伪物料 Mixin。
    """
    # ---------- 封面 ----------
    def set_cover(
        self,
        image_path: str,
        *,
        copy_to_draft: bool = True,
    ) -> bool:
        """
        设置草稿的静态封面图。

        封面会在剪映的草稿列表中显示。支持任意图片格式（PNG/JPG/JPEG/WEBP）。

        Args:
            image_path: 封面图片的本地路径
            copy_to_draft: 是否将图片复制到草稿目录下（推荐 True，避免路径失效）

        Returns:
            成功返回 True，失败返回 False
        """
        if not os.path.exists(image_path):
            print(f"⚠️ Cover image not found: {image_path}")
            return False

        cover_filename = None

        if copy_to_draft:
            draft_dir = os.path.join(self.root, self.name)
            os.makedirs(draft_dir, exist_ok=True)
            ext = os.path.splitext(image_path)[1] or ".png"
            cover_filename = f"cover{ext}"
            cover_dest = os.path.join(draft_dir, cover_filename)
            try:
                shutil.copy2(image_path, cover_dest)
                cover_path = cover_dest
            except Exception as e:
                print(f"⚠️ Failed to copy cover image: {e}")
                cover_path = image_path
                cover_filename = os.path.basename(image_path)
        else:
            cover_path = image_path
            cover_filename = os.path.basename(image_path)

        # 写入 draft_content.json 的 static_cover_image_path
        content_path = os.path.join(self.root, self.name, "draft_content.json")
        if os.path.exists(content_path):
            try:
                with open(content_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["static_cover_image_path"] = cover_filename
                with open(content_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception as e:
                print(f"⚠️ Failed to update static_cover_image_path: {e}")
                return False

        # 写入 draft_meta_info.json 的 draft_cover
        meta_path = os.path.join(self.root, self.name, "draft_meta_info.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["draft_cover"] = cover_filename
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)
            except Exception as e:
                print(f"⚠️ Failed to update draft_cover in meta: {e}")
                # meta 更新失败不算致命错误，content 已经成功了

        print(f"🎬 Cover set: {cover_filename}")
        return True

    def set_cover_from_frame(
        self,
        frame_path: str,
        *,
        copy_to_draft: bool = True,
    ) -> bool:
        """
        设置封面为视频的某一帧（等同 set_cover，语义别名）。

        Args:
            frame_path: 帧截图路径
            copy_to_draft: 是否复制到草稿目录

        Returns:
            成功返回 True
        """
        return self.set_cover(frame_path, copy_to_draft=copy_to_draft)

    # ---------- 调节补丁 ----------
    def _force_activate_adjustments(self):
        content_path = os.path.join(self.root, self.name, "draft_info.json")
        if not os.path.exists(content_path):
            content_path = os.path.join(self.root, self.name, "draft_content.json")
        if not os.path.exists(content_path): return

        try:
            with open(content_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            has_modified = False
            materials = data.setdefault("materials", {})
            all_effects = materials.setdefault("effects", [])

            PROP_MAP = {"KFTypeBrightness": "brightness", "KFTypeContrast": "contrast", "KFTypeSaturation": "saturation"}
            jy_res_path = "C:/Program Files/JianyingPro/5.9.0.11632/Resources/DefaultAdjustBundle/combine_adjust"

            for track in data.get("tracks", []):
                for seg in track.get("segments", []):
                    kfs = seg.get("common_keyframes", [])
                    active_props = [kf.get("property_type") for kf in kfs if kf.get("property_type") in PROP_MAP]

                    if active_props:
                        seg["enable_adjust"] = True
                        seg["enable_color_correct_adjust"] = True
                        refs = seg.setdefault("extra_material_refs", [])

                        for prop in active_props:
                            mat_type = PROP_MAP[prop]
                            if not any(m.get("type") == mat_type and m["id"] in refs for m in all_effects):
                                new_id = str(uuid.uuid4()).upper()
                                shadow_mat = {
                                    "type": mat_type, "value": 0.0, "path": jy_res_path, "id": new_id,
                                    "apply_target_type": 0, "platform": "all", "source_platform": 0, "version": "v2"
                                }
                                all_effects.append(shadow_mat)
                                refs.append(new_id)
                                has_modified = True

            if has_modified:
                with open(content_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Force activation failed: {e}")

    def _patch_cloud_material_ids(self):
        content_path = os.path.join(self.root, self.name, "draft_info.json")
        if not os.path.exists(content_path):
            content_path = os.path.join(self.root, self.name, "draft_content.json")
        if not os.path.exists(content_path): return

        try:
            with open(content_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            has_modified = False
            materials = data.get("materials", {})

            # --- 音频云素材补丁 ---
            audios = materials.get("audios", [])
            for mat in audios:
                path = mat.get("path", "")
                for dummy_path, patch_info in self._cloud_audio_patches.items():
                    if dummy_path in path:
                        if patch_info["type"] == "music":
                            mat["music_id"] = patch_info["id"]
                            mat["type"] = "music"
                            has_modified = True

            if has_modified:
                with open(content_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
