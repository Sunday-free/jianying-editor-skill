"""
独立 TTS 语音合成测试 - 不依赖 JyProject
用法: python examples/test_tts.py [输出目录，默认 ./output_tts]

环境变量:
  JY_TTS_INSECURE_SSL=1  → 跳过 SAMI 的 SSL 证书验证 (默认启用)
"""
import asyncio
import os
import subprocess
import sys

# 跳过 SAMI 的 SSL 证书验证 (解决自签名证书问题)
os.environ.setdefault("JY_TTS_INSECURE_SSL", "1")

# 将 scripts 目录加入路径，确保可以 import universal_tts
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scripts.universal_tts import generate_voice_with_meta


async def test_single(text: str, output_path: str, speaker: str):
    """测试单句合成，返回带后端信息的版本"""
    print(f"\n{'='*60}")
    print(f"  文本: {text}")
    print(f"  音色: {speaker}")
    print(f"  输出: {output_path}")
    print(f"{'='*60}")

    path, backend = await generate_voice_with_meta(
        text=text,
        output_path=output_path,
        speaker=speaker,
        backend=None,            # 自动选择
        allow_fallback=True,     # SAMI 失败自动切换 Edge
        sami_retries=2,
    )

    if not path:
        print(f"  ❌ 失败!")
        return path, backend

    # OGG 转 WAV（OGG 为临时文件，转换后删除）
    wav_path = path.replace('.ogg', '.wav')
    subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-acodec", "pcm_s16le", wav_path],
        capture_output=True, check=True
    )
    os.remove(path)  # 删除临时 OGG

    size_kb = os.path.getsize(wav_path) / 1024
    print(f"  ✅ 成功! 后端: {backend}, 文件: {wav_path} ({size_kb:.1f} KB)")
    return wav_path, backend


async def main():
    # ---- 配置输出目录 ----
    output_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(__file__)
    output_dir = os.path.abspath(os.path.join(output_dir, "..", "output_tts"))
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 输出目录: {output_dir}")

    JINAYING_SPEAKERS = [
        {"name": "真人播客男", "speaker": "zh_male_dayi_saturn_bigtts", "resource_id": "7516817692729331007"},
        {"name": "真人播客女", "speaker": "zh_female_mizai_saturn_bigtts", "resource_id": "7516816955475512615"},
        {"name": "真人新闻主播女", "speaker": "saturn_zh_female_xinwenzhubo", "resource_id": "7571673457126083850"},
        {"name": "三刀（解说）", "speaker": "saturn_zh_male_baichequanshu_jianying", "resource_id": "7597722719471488307"},
        # {"name": "沉稳龙哥", "speaker": "DiT_zh_male_zmtlongjiang_jianying", "resource_id": "7541318859341499686"},
        # {"name": "成熟大哥", "speaker": "ICL_zh_male_denghaorong", "resource_id": "7478206321985065522"},
        # {"name": "强势大佬", "speaker": "zh_male_iclvop_xiaolinhuangshang", "resource_id": "7393243878066754100"},
        # {"name": "威严老爷子", "speaker": "zh_male_laotouzhsk_emo_v2_mars_bigtts", "resource_id": "7452616134727045658"},
        # {"name": "乙游霸总", "speaker": "ICL_zh_male_zjxqinche", "resource_id": "7405796797261550114"},
    ]

    text = "我每天都会帮大家拆解当下的行情，并提前附上可以潜伏的低位新秀，明天周五更明确、更具体的信号，以及大家真正需要的东西，我直接放在我的主页粉丝群了，你现在就去领走，这不是画饼，是你拿了就能用的作战图！我早就说过，我帮不了全天下的散户，但我一定会拼尽全力，让每一位信任我的粉丝都成为今年最幸福的散户。"
    test_cases = [
        (text, jianying_speaker["speaker"], jianying_speaker["name"])
        for jianying_speaker in JINAYING_SPEAKERS
    ]

    results = []
    for i, (text, speaker, name) in enumerate(test_cases, 1):
        output_path = os.path.join(output_dir, f"{name}.ogg")
        path, backend = await test_single(text, output_path, speaker)
        if not path:
            raise Exception(f"universal_tts.generate_voice failed for role={name}")
        results.append((path, backend))

    # ---- 汇总 ----
    print(f"\n{'='*60}")
    print("  📊 测试汇总")
    print(f"{'='*60}")
    success = sum(1 for r in results if r[0])
    print(f"  成功: {success}/{len(results)}")
    for i, (path, backend) in enumerate(results):
        status = "✅" if path else "❌"
        print(f"  {status} 用例{i+1}: {path or '无输出'} (后端: {backend or 'N/A'})")


if __name__ == "__main__":
    asyncio.run(main())
