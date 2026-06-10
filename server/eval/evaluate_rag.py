"""
RAG 评估脚本 — 离线评估检索质量。

用法：
    cd server
    python -m eval.evaluate_rag

指标：
    1. Context Precision  — 检索结果中相关商品占比
    2. Context Recall     — 相关商品被检索到的比例
    3. Hit Rate           — top-K 中至少有一个相关商品的比例
    4. MRR                — 第一个相关商品排名的倒数均值
    5. Category Accuracy  — 类目过滤准确率

依赖：
    pip install ragas datasets  # 可选，基础指标不依赖
"""
import json
import os
import sys
import time
from pathlib import Path

# 确保 server 目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()


def compute_basic_metrics(results: list[dict]) -> dict:
    """
    计算基础检索指标（不依赖 ragas）。

    每个 result 包含：
        query, retrieved_ids, retrieved_categories,
        expected_category, expected_keywords,
        latency_ms, hit_count
    """
    total = len(results)
    if total == 0:
        return {"error": "no results"}

    category_correct = 0
    keyword_hits = 0
    total_precision = 0.0
    total_hit_rate = 0.0
    total_mrr = 0.0
    total_latency = 0.0
    total_hits = 0
    queries_with_results = 0

    for r in results:
        # 类目准确率
        if r.get("expected_category"):
            retrieved_cats = r.get("retrieved_categories", [])
            if any(r["expected_category"] in cat for cat in retrieved_cats):
                category_correct += 1

        # 关键词命中
        keywords = r.get("expected_keywords", [])
        if keywords:
            retrieved_titles = " ".join(r.get("retrieved_titles", []))
            match_count = sum(1 for kw in keywords if kw in retrieved_titles)
            keyword_hits += match_count / len(keywords)

        # Precision@K
        hit_count = r.get("hit_count", 0)
        k = max(len(r.get("retrieved_ids", [])), 1)
        total_precision += hit_count / k

        # Hit Rate
        if hit_count > 0:
            total_hit_rate += 1
            queries_with_results += 1

        # MRR
        mrr = r.get("first_relevant_rank", 0)
        if mrr > 0:
            total_mrr += 1.0 / mrr

        total_latency += r.get("latency_ms", 0)
        total_hits += hit_count

    return {
        "total_queries": total,
        "queries_with_results": queries_with_results,
        "category_accuracy": category_correct / total,
        "keyword_recall": keyword_hits / total,
        "mean_precision": total_precision / total,
        "hit_rate": total_hit_rate / total,
        "mrr": total_mrr / total,
        "avg_latency_ms": total_latency / total,
        "avg_hits_per_query": total_hits / total,
    }


def evaluate(retriever, test_queries: list[dict]) -> list[dict]:
    """运行评估"""
    results = []

    for tc in test_queries:
        query = tc["query"]
        expected_cat = tc.get("expected_category")
        expected_kw = tc.get("expected_keywords", [])
        max_price = tc.get("max_price")

        t0 = time.time()
        try:
            products = retriever.search(
                query,
                top_k=5,
                category_filter=expected_cat if expected_cat else None,
            )
        except Exception as e:
            print(f"  ❌ 搜索失败: {e}")
            products = []
        latency = (time.time() - t0) * 1000

        retrieved_ids = [p.id for p in products]
        retrieved_titles = [p.title for p in products]
        retrieved_cats = [getattr(p, 'category', '') for p in products]
        retrieved_prices = [getattr(p, 'base_price', 0) for p in products]

        # 计算命中数（标题中包含至少一个关键词）
        hit_count = 0
        first_relevant_rank = 0
        titles_text = " ".join(retrieved_titles)
        for i, title in enumerate(retrieved_titles, 1):
            if any(kw in title for kw in expected_kw):
                hit_count += 1
                if first_relevant_rank == 0:
                    first_relevant_rank = i

        # 价格过滤检查
        price_filter_ok = True
        if max_price:
            price_filter_ok = all(p <= max_price for p in retrieved_prices if p > 0)

        result = {
            "query": query,
            "retrieved_ids": retrieved_ids,
            "retrieved_titles": retrieved_titles,
            "retrieved_categories": retrieved_cats,
            "expected_category": expected_cat,
            "expected_keywords": expected_kw,
            "latency_ms": round(latency, 1),
            "hit_count": hit_count,
            "first_relevant_rank": first_relevant_rank,
            "price_filter_ok": price_filter_ok,
        }
        results.append(result)

        status = "✅" if hit_count >= tc.get("min_expected_products", 1) else "⚠️"
        print(f"  {status} '{query[:40]}' → {len(products)} 结果, {hit_count} 命中, {latency:.0f}ms")

    return results


def print_report(metrics: dict, results: list[dict]):
    """打印评估报告"""
    print("\n" + "=" * 60)
    print("  📊 RAG 评估报告")
    print("=" * 60)

    if "error" in metrics:
        print(f"  ❌ {metrics['error']}")
        return

    print(f"""
  📋 基础指标
  ─────────────────────────────────────────
  查询总数:           {metrics['total_queries']}
  有结果查询:         {metrics['queries_with_results']}
  类目准确率:         {metrics['category_accuracy']:.1%}
  关键词召回率:       {metrics['keyword_recall']:.1%}
  平均 Precision@5:   {metrics['mean_precision']:.3f}
  Hit Rate:           {metrics['hit_rate']:.1%}
  MRR:                {metrics['mrr']:.3f}
  平均延迟:           {metrics['avg_latency_ms']:.0f}ms
  平均命中/查询:      {metrics['avg_hits_per_query']:.1f}
""")

    # 逐查询详情
    print("  📋 逐查询详情")
    print("  " + "-" * 56)
    for r in results:
        status = "✅" if r["hit_count"] >= 1 else "❌"
        titles_preview = "、".join(r["retrieved_titles"][:3]) or "(无)"
        print(f"  {status} [{r['latency_ms']:4.0f}ms] {r['query'][:35]:35s} → {titles_preview[:50]}")

    print()


def main():
    print("🔍 加载商品数据...")
    from utils.product_repo import product_repo
    product_repo.load()
    print(f"   {product_repo.count} 个商品")

    print("🔍 初始化检索器...")
    from rag.retriever import ProductRetriever
    retriever = ProductRetriever()
    retriever.initialize()

    print("\n🔍 加载测试集...")
    test_file = Path(__file__).parent / "test_queries.json"
    with open(test_file, "r", encoding="utf-8") as f:
        test_queries = json.load(f)
    print(f"   {len(test_queries)} 条测试查询")

    print("\n🔍 运行评估...")
    results = evaluate(retriever, test_queries)

    print("\n🔍 计算指标...")
    metrics = compute_basic_metrics(results)

    print_report(metrics, results)

    # 保存结果
    output_file = Path(__file__).parent / "eval_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"📁 结果已保存至: {output_file}")


if __name__ == "__main__":
    main()
