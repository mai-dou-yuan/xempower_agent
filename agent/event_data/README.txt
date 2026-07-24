"D:\xempower_agent\agent\event_data\predictions.csv" 文件说明
本目录保存两套模型预测结果合并后的数据：
1. 出拳接触结果预测（是否命中、被格挡或未命中）
2. 出拳类型预测（例如前手直拳、勾拳、上勾拳）

文件：predictions.csv
- 每一行表示一次已标注的出拳事件，共 318 条。
- 记录按 event_id 合并：同一行中的两类预测对应同一次出拳、同一个视频和同一组关键帧。

事件与 GT（人工标注）字段
- event_id：事件唯一编号。
- video_id / video_name：事件所属视频。
- fighter：出拳方（red 或 blue）。
- start_frame、peak_frame、contact_frame、end_frame：出拳关键帧位置。
- punch_type：人工标注的真实拳型（GT）。
- contact_outcome：人工标注的真实接触结果（GT）。

模型预测字段
- pred_punch_type：拳型模型预测的拳型。
- pred_punch_type_confidence：拳型预测置信度（通常为 0 到 1）。
- pred_contact_outcome：接触结果模型的预测，取值为 landed（命中）、blocked（被格挡）或 missed（未命中）。
- pred_contact_outcome_confidence：接触结果预测置信度（通常为 0 到 1）。

使用方式
- 比较 punch_type 与 pred_punch_type，可评估拳型模型。
- 比较 contact_outcome 与 pred_contact_outcome，可评估接触结果模型。
- 两类置信度越高表示模型越确信，但不等于预测一定正确。
