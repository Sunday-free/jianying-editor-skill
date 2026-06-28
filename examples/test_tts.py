"""
独立 TTS 语音合成测试 - 不依赖 JyProject
用法: python examples/test_tts.py [输出目录，默认 ./output_tts]

环境变量:
  JY_TTS_INSECURE_SSL=1  → 跳过 SAMI 的 SSL 证书验证 (默认启用)
"""
import asyncio
import os
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

    # ---- 测试用例 ----
    test_cases = [
        ("你好，欢迎使用智能语音合成系统。", "zh_male_huoli"),
        ("今天天气真不错，适合出去散步。", "zh_female_xiaopengyou"),
        ("人工智能正在改变我们的生活方式。", "BV408_streaming"),
    ]

    results = []
    for i, (text, speaker) in enumerate(test_cases, 1):
        output_path = os.path.join(output_dir, f"test_{i}_{speaker}.ogg")
        result = await test_single(text, output_path, speaker)
        results.append(result)

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
