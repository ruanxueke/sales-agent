#!/usr/bin/env bash
# 全量验证：跑所有轮次的验证脚本
set -e
cd /opt/sales-agent

for f in verify_enterprise_round.sh verify_bi_round.sh verify_sales_flow_round.sh verify_wecom_round.sh verify_commercial_round.sh verify_vision_round.sh; do
  if [ -f "/opt/sales-agent/deploy/$f" ]; then
    echo "==> $f"
    bash "/opt/sales-agent/deploy/$f" || echo "!! $f 有失败项"
  fi
done

echo "全量验证完成"
