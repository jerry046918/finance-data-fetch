#!/usr/bin/env python3
"""
本地测试脚本：验证基金数据采集功能
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from fetch_fund_data import FundDataCollector, map_fund_type_to_asset_class


def quick_test():
    print("🚀 开始本地环境测试...")
    
    # 初始化收集器
    collector = FundDataCollector(db_path="test_funds.db")
    
    try:
        # 测试 1: 获取基金列表
        print("\n📋 测试 1: 获取基金列表")
        fund_df = collector.get_fund_list()
        print(f"   ✅ 获取到 {len(fund_df)} 只基金")
        
        # 测试 2: 类型映射
        print("\n📋 测试 2: 基金类型映射")
        test_types = ['混合型-偏股', '债券型-长债', '货币型-普通货币', 'QDII-普通股票', 'FOF-稳健型']
        for t in test_types:
            asset_class = map_fund_type_to_asset_class(t)
            print(f"   {t} -> {asset_class}")
        
        # 测试 3: 净值获取
        print("\n📋 测试 3: 获取净值数据")
        test_codes = ['000001', '000002', '000003']
        nav_data = collector.fetch_nav_data(test_codes)
        for code, data in nav_data.items():
            print(f"   {code}: nav={data['nav']}, date={data['date']}")
        
        # 测试 4: 完整流程（限制 10 只）
        print("\n📋 测试 4: 完整流程（10 只基金）")
        collector2 = FundDataCollector(db_path="test_funds.db")
        df = collector2.process_funds(limit=10)
        print(f"   ✅ 处理 {len(df)} 条记录")
        print(f"\n   示例数据:")
        for _, row in df.head(3).iterrows():
            print(f"   {row['fund_code']} {row['fund_name']}: {row['fund_type']} -> {row['asset_class']}")
        
        collector2.save_to_database(df)
        
        # 测试 5: 数据库查询
        print("\n📋 测试 5: 数据库查询")
        collector2.cursor.execute("SELECT COUNT(*) FROM funds")
        count = collector2.cursor.fetchone()[0]
        print(f"   ✅ 数据库中有 {count} 条记录")
        
        collector2.close()
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        collector.close()
    
    print("\n🎉 环境测试通过！")
    return True


if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)
