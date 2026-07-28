#!/usr/bin/env python3
"""
行为进化引擎 - Behavior Evolution Engine
让Agent从经验中自动提炼行为规则，实现记忆到行为的闭环。

功能：
1. analyze - 分析 corrections/ 目录，检测重复模式
2. suggest - 基于模式检测结果生成规则建议
3. report - 生成行为回顾报告
4. init - 初始化 corrections/ 目录结构

用法：
  python3 behavior_evolution.py init --workspace /path/to/workspace
  python3 behavior_evolution.py analyze --workspace /path/to/workspace [--days 30]
  python3 behavior_evolution.py suggest --workspace /path/to/workspace [--min-count 2]
  python3 behavior_evolution.py report --workspace /path/to/workspace [--days 30]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


def init_workspace(workspace: str):
    """初始化 corrections/ 目录结构"""
    corrections_dir = Path(workspace) / "corrections"
    corrections_dir.mkdir(parents=True, exist_ok=True)
    
    index_file = corrections_dir / "index.json"
    if not index_file.exists():
        index_data = {
            "corrections": [],
            "patterns": {},
            "last_review": None,
            "version": "1.0.0"
        }
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已创建 {index_file}")
    
    # 创建当月文件（如果不存在）
    now = datetime.now()
    monthly_file = corrections_dir / f"{now.strftime('%Y-%m')}.md"
    if not monthly_file.exists():
        with open(monthly_file, "w", encoding="utf-8") as f:
            f.write(f"# 行为纠正记录 - {now.strftime('%Y年%m月')}\n\n")
            f.write("> 本文件记录用户纠正Agent行为的事件，用于模式检测和规则提炼。\n\n")
        print(f"✅ 已创建 {monthly_file}")
    
    print(f"📁 corrections/ 目录已就绪：{corrections_dir}")


def load_corrections(corrections_dir: Path, days: int = 30) -> list:
    """加载指定天数内的纠正记录"""
    cutoff_date = datetime.now() - timedelta(days=days)
    corrections = []
    
    # 从 index.json 加载
    index_file = corrections_dir / "index.json"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            for c in data.get("corrections", []):
                try:
                    c_date = datetime.strptime(c["date"], "%Y-%m-%d")
                    if c_date >= cutoff_date:
                        corrections.append(c)
                except (ValueError, KeyError):
                    continue
    
    # 从月度 .md 文件解析
    for md_file in sorted(corrections_dir.glob("*.md")):
        # 从文件名解析年月
        match = re.match(r"(\d{4})-(\d{2})", md_file.stem)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            # 检查该月是否在范围内
            month_start = datetime(year, month, 1)
            if month_start >= cutoff_date - timedelta(days=31):  # 宽裕一点
                content = md_file.read_text(encoding="utf-8")
                # 解析 markdown 中的纠正记录
                entries = parse_markdown_corrections(content, cutoff_date)
                corrections.extend(entries)
    
    # 去重（基于 id 或 date+trigger）
    seen = set()
    unique = []
    for c in corrections:
        key = c.get("id") or f"{c.get('date', '')}:{c.get('trigger', '')[:50]}"
        if key not in seen:
            seen.add(key)
            unique.append(c)
    
    return unique


def parse_markdown_corrections(content: str, cutoff_date: datetime) -> list:
    """从 markdown 文件中解析纠正记录"""
    entries = []
    # 匹配 ## 日期 标题 格式
    pattern = r"##\s+(\d{4}-\d{2}-\d{2})\s*(.*?)\n((?:[-\s].*?\n)*)"
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        date_str = match.group(1)
        title = match.group(2).strip()
        body = match.group(3).strip()
        
        try:
            entry_date = datetime.strptime(date_str, "%Y-%m-%d")
            if entry_date < cutoff_date:
                continue
        except ValueError:
            continue
        
        entry = {
            "date": date_str,
            "source": title or "用户纠正",
            "trigger": "",
            "agent_action": "",
            "user_correction": "",
            "severity": "P1",  # 默认
            "pattern": "",
        }
        
        # 解析各字段
        for line in body.split("\n"):
            line = line.strip("- ").strip()
            if line.startswith("触发情境") or line.startswith("触发"):
                entry["trigger"] = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            elif line.startswith("Agent行为") or line.startswith("agent"):
                entry["agent_action"] = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            elif line.startswith("用户纠正") or line.startswith("纠正"):
                entry["user_correction"] = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            elif line.startswith("影响级别") or line.startswith("级别"):
                severity_match = re.search(r"P[012]", line)
                if severity_match:
                    entry["severity"] = severity_match.group()
        
        if entry["trigger"] or entry["user_correction"]:
            entries.append(entry)
    
    return entries


def detect_patterns(corrections: list) -> dict:
    """检测纠正记录中的重复模式"""
    # 按 pattern 字段聚类
    pattern_groups = defaultdict(list)
    
    for c in corrections:
        # 如果有明确的 pattern 字段，直接用
        if c.get("pattern"):
            pattern_groups[c["pattern"]].append(c)
        else:
            # 基于关键词做简单聚类
            # 实际使用时应该用 LLM 做语义聚类
            keywords = extract_keywords(c.get("trigger", "") + " " + c.get("user_correction", ""))
            for kw in keywords:
                pattern_groups[kw].append(c)
    
    # 过滤：只保留出现 >= 2 次的模式
    significant_patterns = {}
    for pattern, items in pattern_groups.items():
        if len(items) >= 2:
            dates = sorted(set(item.get("date", "") for item in items))
            significant_patterns[pattern] = {
                "count": len(items),
                "items": items,
                "first_seen": dates[0] if dates else "unknown",
                "last_seen": dates[-1] if dates else "unknown",
                "severity_distribution": count_severity(items)
            }
    
    return significant_patterns


def extract_keywords(text: str) -> list:
    """简单关键词提取（用于初步聚类）"""
    # 移除常见停用词
    stopwords = {"的", "了", "是", "在", "我", "你", "他", "和", "与", "或", "不", "也", "就", "都", "要", "会", "能", "可以", "应该"}
    
    # 分词（简单按空格和标点分）
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text)
    
    # 过滤
    keywords = [t for t in tokens if len(t) >= 2 and t not in stopwords]
    
    # 返回 top 3 关键词
    return keywords[:3]


def count_severity(items: list) -> dict:
    """统计各级别数量"""
    counts = defaultdict(int)
    for item in items:
        severity = item.get("severity", "P1")
        counts[severity] += 1
    return dict(counts)


def analyze(workspace: str, days: int = 30):
    """分析纠正记录，检测重复模式"""
    corrections_dir = Path(workspace) / "corrections"
    if not corrections_dir.exists():
        print(f"❌ corrections/ 目录不存在：{corrections_dir}")
        print("请先运行 init 命令初始化")
        return
    
    corrections = load_corrections(corrections_dir, days)
    
    if not corrections:
        print(f"📊 最近 {days} 天内没有纠正记录")
        return
    
    print(f"📊 最近 {days} 天内共 {len(corrections)} 条纠正记录：")
    print()
    
    # 按严重程度分布
    severity_dist = count_severity(corrections)
    print("严重程度分布：")
    for sev in ["P0", "P1", "P2"]:
        if sev in severity_dist:
            print(f"  {sev}: {severity_dist[sev]} 条")
    print()
    
    # 检测模式
    patterns = detect_patterns(corrections)
    
    if patterns:
        print(f"🔄 检测到 {len(patterns)} 个重复模式：")
        print()
        
        # 按出现次数排序
        sorted_patterns = sorted(patterns.items(), key=lambda x: x[1]["count"], reverse=True)
        
        for i, (pattern_name, info) in enumerate(sorted_patterns, 1):
            count = info["count"]
            level = "🔴 高频" if count >= 3 else "🟡 重复"
            print(f"  {i}. {level} [{pattern_name}] — 出现 {count} 次")
            print(f"     首次：{info['first_seen']}  最近：{info['last_seen']}")
            # 展示最近一条的具体内容
            latest = info["items"][-1]
            if latest.get("user_correction"):
                print(f"     最近纠正：{latest['user_correction'][:80]}")
            print()
    else:
        print("✅ 暂未检测到重复模式（所有纠正均为独立事件）")
    
    return corrections, patterns


def suggest(workspace: str, min_count: int = 2):
    """基于模式检测生成规则建议"""
    corrections_dir = Path(workspace) / "corrections"
    if not corrections_dir.exists():
        print(f"❌ corrections/ 目录不存在")
        return
    
    corrections = load_corrections(corrections_dir, days=90)
    patterns = detect_patterns(corrections)
    
    suggestions = []
    
    for pattern_name, info in patterns.items():
        if info["count"] < min_count:
            continue
        
        # 从相关纠正中提炼规则
        items = info["items"]
        # 取最新的纠正内容作为规则基础
        latest = max(items, key=lambda x: x.get("date", ""))
        
        correction_text = latest.get("user_correction", "")
        if not correction_text:
            continue
        
        # 生成规则建议
        rule_text = correction_text
        # 清理措辞
        rule_text = re.sub(r"^(以后|记住|不要|别再|必须|一定要)", "", rule_text).strip()
        if rule_text and not rule_text.endswith("。"):
            rule_text += "。"
        
        # 判断写入位置
        target_file = infer_target_file(pattern_name, items)
        
        suggestion = {
            "pattern": pattern_name,
            "count": info["count"],
            "rule_title": pattern_name,
            "rule_text": rule_text,
            "target_file": target_file,
            "evidence_dates": sorted(set(item.get("date", "") for item in items)),
            "evidence_count": info["count"]
        }
        suggestions.append(suggestion)
    
    if not suggestions:
        print("✅ 暂无新的规则建议")
        return
    
    print("📋 规则建议：")
    print()
    for i, s in enumerate(suggestions, 1):
        level = "🔴 强烈建议" if s["count"] >= 3 else "🟡 建议"
        print(f"  {i}. {level} [{s['rule_title']}]（出现 {s['count']} 次）")
        print(f"     规则内容：{s['rule_text']}")
        print(f"     建议写入：{s['target_file']}")
        print(f"     证据日期：{', '.join(s['evidence_dates'])}")
        print()
    
    return suggestions


def infer_target_file(pattern_name: str, items: list) -> str:
    """根据模式内容推断应该写入哪个配置文件"""
    keywords = pattern_name.lower()
    combined_text = " ".join(item.get("trigger", "") + item.get("user_correction", "") for item in items).lower()
    
    # 工具/平台相关
    if any(kw in combined_text for kw in ["工具", "脚本", "命令", "接口", "api", "脚本", "平台"]):
        return "TOOLS.md"
    
    # 用户偏好相关
    if any(kw in combined_text for kw in ["用户", "偏好", "喜欢", "不喜欢", "称呼"]):
        return "USER.md"
    
    # 身份/风格相关
    if any(kw in combined_text for kw in ["性格", "说话", "风格", "语气", "态度"]):
        return "SOUL.md"
    
    # 默认写入 MEMORY.md
    return "MEMORY.md"


def generate_report(workspace: str, days: int = 30):
    """生成完整的行为回顾报告"""
    corrections_dir = Path(workspace) / "corrections"
    
    corrections = load_corrections(corrections_dir, days) if corrections_dir.exists() else []
    
    report_lines = []
    report_lines.append(f"# 📋 行为规则回顾报告")
    report_lines.append(f"")
    report_lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"**回顾范围**：最近 {days} 天")
    report_lines.append(f"**纠正记录数**：{len(corrections)}")
    report_lines.append(f"")
    
    # 统计
    if corrections:
        severity_dist = count_severity(corrections)
        report_lines.append("## 纠正统计")
        report_lines.append("")
        for sev in ["P0", "P1", "P2"]:
            if sev in severity_dist:
                report_lines.append(f"- {sev}: {severity_dist[sev]} 条")
        report_lines.append("")
        
        # 模式检测
        patterns = detect_patterns(corrections)
        if patterns:
            report_lines.append("## 🔄 检测到的重复模式")
            report_lines.append("")
            for pattern_name, info in sorted(patterns.items(), key=lambda x: x[1]["count"], reverse=True):
                report_lines.append(f"### {pattern_name}（{info['count']} 次）")
                report_lines.append(f"- 首次出现：{info['first_seen']}")
                report_lines.append(f"- 最近出现：{info['last_seen']}")
                latest = info["items"][-1]
                if latest.get("user_correction"):
                    report_lines.append(f"- 最近纠正：{latest['user_correction'][:100]}")
                report_lines.append("")
    
    # 检查现有规则文件（支持多种目录结构）
    report_lines.append("## 📂 现有规则文件扫描")
    report_lines.append("")
    
    config_files = ["SOUL.md", "MEMORY.md", "TOOLS.md", "USER.md"]
    search_dirs = ["", "基础设定", "config", ".agent"]  # 常见目录结构
    
    for cf in config_files:
        found = False
        for search_dir in search_dirs:
            cf_path = Path(workspace) / search_dir / cf if search_dir else Path(workspace) / cf
            if cf_path.exists():
                content = cf_path.read_text(encoding="utf-8")
                rule_count = content.count("- **")
                rel_path = f"{search_dir}/{cf}" if search_dir else cf
                report_lines.append(f"- {rel_path}: 存在，约 {rule_count} 条规则")
                found = True
                break
        if not found:
            report_lines.append(f"- {cf}: 不存在")
    
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("*本报告由行为进化引擎自动生成*")
    
    report_text = "\n".join(report_lines)
    
    # 保存报告
    report_path = Path(workspace) / "corrections" / f"report_{datetime.now().strftime('%Y%m%d')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    
    print(report_text)
    print(f"\n📄 报告已保存：{report_path}")
    
    return report_text


def main():
    parser = argparse.ArgumentParser(description="行为进化引擎 - 让Agent从经验中提炼行为规则")
    parser.add_argument("command", choices=["init", "analyze", "suggest", "report", "verify_pointers"],
                       help="执行命令：init=初始化, analyze=分析模式, suggest=生成建议, report=生成报告, verify_pointers=验证指针有效性")
    parser.add_argument("--workspace", "-w", required=True, help="Agent 工作区路径")
    parser.add_argument("--days", "-d", type=int, default=30, help="回顾天数（默认30）")
    parser.add_argument("--min-count", "-m", type=int, default=2, help="最小出现次数（默认2）")
    
    args = parser.parse_args()
    
    if args.command == "init":
        init_workspace(args.workspace)
    elif args.command == "analyze":
        analyze(args.workspace, args.days)
    elif args.command == "suggest":
        suggest(args.workspace, args.min_count)
    elif args.command == "report":
        generate_report(args.workspace, args.days)
    elif args.command == "verify_pointers":
        verify_pointers(args.workspace)


def verify_pointers(workspace: str):
    """验证 MEMORY.md 中强制检索规则表的指针有效性"""
    memory_paths = [
        Path(workspace) / "MEMORY.md",
        Path(workspace) / "基础设定" / "MEMORY.md",
    ]
    
    memory_file = None
    for p in memory_paths:
        if p.exists():
            memory_file = p
            break
    
    if not memory_file:
        print("❌ 未找到 MEMORY.md")
        return
    
    content = memory_file.read_text(encoding="utf-8")
    
    # 解析强制检索规则表
    # 匹配表格行：| 关键词 | `路径1` + `路径2` | 说明 |  或  | 关键词 | `路径` | 说明 |
    table_pattern = r"\|\s*(.+?)\s*\|(.+?)\|\s*(.+?)\s*\|"
    
    # 找到强制检索规则表区域
    in_section = False
    pointers = []
    
    for line in content.split("\n"):
        if "强制检索规则" in line:
            in_section = True
            continue
        if in_section:
            # 遇到新的 ## 标题则退出
            if line.startswith("## ") and "强制检索" not in line:
                break
            match = re.match(table_pattern, line)
            if match:
                keywords = match.group(1).strip()
                raw_paths = match.group(2).strip()
                description = match.group(3).strip()
                # 跳过表头
                if keywords in ("触发关键词", "---") or raw_paths.startswith("---"):
                    continue
                # 从 raw_paths 中提取所有 `path` 格式的路径
                paths = re.findall(r"`([^`]+)`", raw_paths)
                if not paths:
                    # 兜底：如果没反引号，直接用原始内容
                    paths = [raw_paths.strip()]
                file_path_display = " + ".join(paths)
                pointers.append({
                    "keywords": keywords,
                    "file_path": file_path_display,
                    "paths": paths,
                    "description": description,
                })
    
    if not pointers:
        print("✅ 未找到强制检索规则表，或表中无条目")
        return
    
    print(f"🔍 扫描到 {len(pointers)} 个强制检索指针：\n")
    
    valid = 0
    broken = 0
    stale = 0
    
    for ptr in pointers:
        file_path_display = ptr["file_path"]
        paths = ptr.get("paths", [file_path_display])
        
        all_exist = True
        newest_mtime = None
        
        for p in paths:
            p = p.strip()
            full_path = Path(workspace) / p
            if full_path.exists():
                mtime = full_path.stat().st_mtime
                if newest_mtime is None or mtime > newest_mtime:
                    newest_mtime = mtime
            else:
                all_exist = False
        
        if not all_exist:
            status = "❌ 文件不存在"
            broken += 1
        elif newest_mtime:
            days_old = (datetime.now() - datetime.fromtimestamp(newest_mtime)).days
            if days_old > 30:
                status = f"⚠️ {days_old}天未更新"
                stale += 1
            else:
                status = f"✅ 正常（{days_old}天前更新）"
                valid += 1
        else:
            status = "✅ 存在"
            valid += 1
        
        print(f"  [{ptr['keywords']}]")
        print(f"    → {file_path_display}")
        print(f"    {status}")
        print()
    
    # 汇总
    print("---")
    print(f"📊 汇总：✅ {valid} 正常 | ⚠️ {stale} 过期 | ❌ {broken} 失效")
    
    if broken > 0:
        print("\n⚠️ 建议：删除或修复失效指针，避免触发时读取失败")
    if stale > 0:
        print("\n💡 建议：检查过期文件内容是否仍有效，必要时更新路径指向最新版本")


if __name__ == "__main__":
    main()
