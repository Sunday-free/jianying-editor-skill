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

    if path:
        size_kb = os.path.getsize(path) / 1024
        print(f"  ✅ 成功! 后端: {backend}, 文件: {path} ({size_kb:.1f} KB)")
    else:
        print(f"  ❌ 失败!")
    return path, backend


async def main():
    # ---- 配置输出目录 ----
    output_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "output_tts"
    )
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 输出目录: {os.path.abspath(output_dir)}")

    JINAYING_SPEAKERS = [
        {"name": "真人播客男", "speaker": "zh_male_dayi_saturn_bigtts", "resource_id": "7516817692729331007"},
        {"name": "真人播客女", "speaker": "zh_female_mizai_saturn_bigtts", "resource_id": "7516816955475512615"},
        {"name": "真人新闻主播女", "speaker": "saturn_zh_female_xinwenzhubo", "resource_id": "7571673457126083850"},
        {"name": "三刀（解说）", "speaker": "saturn_zh_male_baichequanshu_jianying", "resource_id": "7597722719471488307"},
        {"name": "沉稳龙哥", "speaker": "DiT_zh_male_zmtlongjiang_jianying", "resource_id": "7541318859341499686"},
        {"name": "成熟大哥", "speaker": "ICL_zh_male_denghaorong", "resource_id": "7478206321985065522"},
        {"name": "强势大佬", "speaker": "zh_male_iclvop_xiaolinhuangshang", "resource_id": "7393243878066754100"},
        {"name": "威严老爷子", "speaker": "zh_male_laotouzhsk_emo_v2_mars_bigtts", "resource_id": "7452616134727045658"},
        {"name": "乙游霸总", "speaker": "ICL_zh_male_zjxqinche", "resource_id": "7405796797261550114"},
    ]

    text = "突发重磅变盘信号！周二开盘赶紧撤，这可不是闹着玩的。A股将直面2026年烈度最强的一次变盘没有例外。这轮盘面放量根本不是什么行情回暖的确认信号，恰恰相反，这是主力彻底装了，直接把真实动向摆上了台面。"
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

        # OGG 转 WAV
        wav_path = path.replace('.ogg', '.wav')
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-acodec", "pcm_s16le", wav_path],
            capture_output=True, check=True
        )
        os.remove(path)  # 删除临时 OGG
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
