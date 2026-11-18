"""
探针脚本：读取视频元数据 + 计算 SHA-256 文件哈希
==================================================
对应需求文档 FR-PARSE-01（P0）：
  读取时长、分辨率、帧率、码率、编码格式、音轨信息、创建时间、文件大小、哈希。

这个脚本只用 Python 自带的标准库，不需要 pip 安装任何东西。
它调用系统里的 ffprobe 命令来获取信息（ffprobe 是 FFmpeg 的一部分，你电脑已装好）。

运行方式（在项目根目录执行）：
  python scripts/probe_video.py
  python scripts/probe_video.py data/samples/sample_test.mp4
"""

# import 就是把别人写好的工具拿过来用。下面这几个都是 Python 自带的。
import subprocess  # 用来在 Python 里执行系统命令（这里执行 ffprobe）
import json        # ffprobe 输出的是 JSON 格式，用它把字符串转成 Python 字典
import hashlib     # 用来计算 SHA-256 哈希（文件的"身份证"）
import sys         # 用来读取命令行参数
from pathlib import Path  # 用来处理文件路径，比字符串拼接更安全


def sha256_of_file(path, chunk_size=1024 * 1024):
    """计算文件的 SHA-256 哈希。

    为什么要分块读？因为素材可能有 100GB，一次性读进内存会爆掉。
    每次读 1MB（1024*1024 字节），读一点算一点，内存始终只占 1MB。
    """
    hasher = hashlib.sha256()          # 创建一个哈希计算器
    with open(path, "rb") as f:        # "rb" = 以二进制只读方式打开
        while True:                     # 循环读，直到文件结束
            chunk = f.read(chunk_size)  # 读一块数据
            if not chunk:               # 读到空数据说明到文件末尾了
                break                   # 跳出循环
            hasher.update(chunk)        # 把这块数据喂给哈希计算器
    return hasher.hexdigest()           # 返回最终的十六进制哈希字符串


def run_ffprobe(path):
    """调用 ffprobe 命令，拿到视频的元数据。

    ffprobe 的参数解释：
      -v error          只输出错误，减少噪音
      -print_format json 让它用 JSON 格式输出（方便程序解析）
      -show_format      显示容器信息（时长、码率、文件大小等）
      -show_streams     显示流信息（视频流、音频流各自的分辨率、编码等）
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    # subprocess.run 执行命令，capture_output=True 表示把输出结果抓回来
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:  # returncode 不为 0 说明命令失败了
        raise RuntimeError(f"ffprobe 执行失败：{result.stderr}")
    return json.loads(result.stdout)  # 把 JSON 字符串转成 Python 字典


def pick_stream(streams, kind):
    """从所有流里挑出第一个指定类型的流（video 或 audio）。"""
    for s in streams:
        if s.get("codec_type") == kind:  # get 是字典的安全取值，取不到返回 None
            return s
    return None  # 没找到就返回 None（比如视频没有音轨）


def probe(path):
    """主函数：读取一个视频文件，整理成我们想要的字段。"""
    path = Path(path)                      # 转成 Path 对象，方便处理路径
    if not path.exists():                  # 先检查文件是否存在
        raise FileNotFoundError(f"找不到文件：{path}")

    info = run_ffprobe(path)               # 调用 ffprobe 拿原始数据
    fmt = info.get("format", {})           # 容器信息
    streams = info.get("streams", [])      # 所有流（视频、音频）
    video = pick_stream(streams, "video")  # 视频流
    audio = pick_stream(streams, "audio")  # 音频流

    # 下面把信息整理成一份"人话"报告。用 or 是因为 ffprobe 某些字段可能缺失。
    report = {
        "文件路径": str(path.resolve()),
        "文件大小(MB)": round(int(fmt.get("size", 0)) / 1024 / 1024, 2),
        "时长(秒)": round(float(fmt.get("duration", 0)), 3),
        "整体码率(kbps)": round(int(fmt.get("bit_rate", 0)) / 1000, 1),
        "容器格式": fmt.get("format_name", "未知"),
        "创建时间": fmt.get("tags", {}).get("creation_time", "无"),
        "SHA-256": sha256_of_file(path),   # 调用上面写的哈希函数
    }
    if video:  # 如果有视频流，补充视频相关字段
        report["视频编码"] = video.get("codec_name", "未知")
        report["分辨率"] = f'{video.get("width", "?")}x{video.get("height", "?")}'
        # 帧率是一个分数，比如 "25/1"，这里简单转成小数
        fps = video.get("avg_frame_rate", "0/1")
        try:
            num, den = fps.split("/")
            report["帧率(fps)"] = round(int(num) / int(den), 2)
        except (ValueError, ZeroDivisionError):
            report["帧率(fps)"] = fps
    if audio:  # 如果有音频流，补充音频相关字段
        report["音频编码"] = audio.get("codec_name", "未知")
        report["音频采样率(Hz)"] = audio.get("sample_rate", "未知")
        report["声道数"] = audio.get("channels", "未知")
    else:
        report["音频编码"] = "无音轨"
    return report


def main():
    """程序入口：决定处理哪个文件，然后打印结果。"""
    # sys.argv 是命令行参数列表。argv[0] 是脚本名，argv[1] 才是第一个参数。
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]  # 用户指定了文件，就处理这些
    else:
        # 没指定参数，就扫描 data/samples 目录下的所有 mp4
        sample_dir = Path(__file__).resolve().parent.parent / "data" / "samples"
        paths = list(sample_dir.glob("*.mp4"))
        if not paths:
            print("没有找到样片。请放一个 mp4 到 data/samples/ 目录，或直接把路径传给脚本。")
            return

    for p in paths:  # 逐个处理
        print("=" * 50)
        try:
            report = probe(p)
            for key, value in report.items():  # 一行行打印"字段：值"
                print(f"  {key}: {value}")
        except Exception as e:  # 捕获所有异常，让单个文件失败不影响其他文件
            print(f"  处理失败 {p.name}: {e}")


# 这是 Python 的固定写法：只有直接运行这个脚本时才执行 main()，
# 被别的脚本 import 时不执行。先记住就行。
if __name__ == "__main__":
    main()
