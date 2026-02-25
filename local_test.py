#!/usr/bin/env python3
"""
本地测试脚本：抓取前5只基金验证环境配置
"""

import sys
import os

# 确保能找到scripts目录下的模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from fetch_fund_data import FundDataCollector

def quick_test():
    print("🚀 开始本地环境测试...")
    
    # 初始化收集器（测试模式）
    collector = FundDataCollector(db_path="test_funds.db")
    
    try:
        # 只获取5只基金做测试
        fund_df = collector.get_fund_list("equity")
        test_funds = fund_df.head(5)
        
        print(f"✅ 成功获取基金列表，选取前 {len(test_funds)} 只测试")
        print("\n测试基金:")
        for _, row in test_funds.iterrows():
            print(f"  - {row['基金代码']}: {row['基金简称']}")
        
        # 获取最新报告期
        quarter = collector.get_latest_quarter()
        print(f"\n📅 目标报告期: {quarter}")
        
        # 测试抓取第一只基金的持仓
        first_code = test_funds.iloc[0]['基金代码']
        print(f"\n🔍 测试抓取 [{first_code}] 的持仓数据...")
        
        holdings = collector.fetch_single_fund_holdings(first_code, quarter)
        
        if not holdings.empty:
            print(f"✅ 成功获取持仓！共 {len(holdings)} 条记录")
            print("\n前3条持仓示例:")
            print(holdings.head(3)[['stock_code', 'stock_name', 'hold_ratio']])
            
            # 保存到测试数据库
            collector.save_to_database([holdings], [{
                'fund_code': first_code,
                'fund_name': test_funds.iloc[0]['基金简称'],
                'fund_type': '测试',
                'latest_nav': 1.0,
                'nav_date': '2024-01-01',
                'update_time': '2024-01-01',
                'quarter': quarter
            }])
            print(f"\n💾 数据已保存到 test_funds.db")
            
            # 验证数据库查询
            collector.cursor.execute("SELECT COUNT(*) FROM holdings")
            count = collector.cursor.fetchone()[0]
            print(f"✅ 数据库验证: 共 {count} 条持仓记录")
            
        else:
            print("⚠️ 未获取到持仓数据（可能是非交易日或季报未披露）")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        collector.close()
        
    print("\n🎉 环境测试通过！可以运行完整抓取了")
    return True

if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)