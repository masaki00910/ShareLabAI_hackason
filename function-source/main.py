import os
import json
import base64
import functions_framework
import vertexai
from google.cloud import storage, bigquery
from vertexai.preview.generative_models import GenerativeModel, Part
import requests 


# Slack 通知用の関数
def send_slack_notification(subject, body):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL が設定されていません")
        return

    # 件名と本文をまとめたメッセージを作成（必要に応じて整形してください）
    message = f"*{subject}*\n{body}"
    payload = {"text": message}

    try:
        response = requests.post(webhook_url, json=payload)
        if response.status_code != 200:
            print(f"Slack通知エラー: {response.status_code} {response.text}")
        else:
            print("Slackに通知を送信しました")
    except Exception as e:
        print(f"Slack通知送信中にエラーが発生しました: {str(e)}")


@functions_framework.cloud_event
def gcs_trigger(cloud_event):
    # CloudEventデータの解析
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    print(f"CloudEventが届きました - bucket: {bucket_name}, file_name: {file_name}")

    # 1. GCS から画像ファイルを取得する
    temp_local_filename = f"/tmp/{file_name}"
    dir_path = os.path.dirname(temp_local_filename)
    os.makedirs(dir_path, exist_ok=True)

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    blob.download_to_filename(temp_local_filename)
    print(f"ファイルをダウンロードしました: {temp_local_filename}")

    # 2. Vertex AI を初期化
    project_id = "sharelabai-hackathon"  # プロジェクトID
    location = "us-central1"            # リージョン
    vertexai.init(project=project_id, location=location)

    try:
        # 3. Gemini 2.0 Flash モデルの初期化
        model = GenerativeModel("gemini-2.0-flash-exp")

        # 4. 画像読み込み、Part オブジェクト作成
        with open(temp_local_filename, "rb") as image_file:
            image_data = image_file.read()
        image_part = Part.from_data(data=image_data, mime_type="image/jpeg")

        # 5. プロンプトを設定し分析実行
        prompt = """あなたは、顔の状態を含めた健康状態を評価する「健康状態アナリストAI」です。次の手順に従い、入力された画像内の人物（もしくは主要な人物）について、以下の4項目が満たされているかどうかを判定してください。 

1. ヘルメットを正しくかぶっているか
2. 髪の毛は短い、あるいは適切にまとめられているか
3. 作業着を着用しているか
4. 安全ベスト（反射ベスト）を着用しているか


【出力フォーマット】
Helmet: [YES / NO / UNCERTAIN]
Hair: [YES / NO / UNCERTAIN]
WorkClothes: [YES / NO / UNCERTAIN]
SafetyVest: [YES / NO / UNCERTAIN]


- "YES" は、その項目が「該当する」または「確認できる」という意味です。
- "NO" は、その項目が「該当しない」または「確認できない」という意味です。
- "UNCERTAIN" は、画像が不鮮明などの理由で「判定が難しい」場合に使用してください。

人物が複数写っている場合は、主要な人物について評価するか、可能であれば人数分の判定を個別に出力してください。
"""
        response = model.generate_content(
            [prompt, image_part],
            generation_config={
                "max_output_tokens": 1024,
                "temperature": 0.4,
            }
        )

        # 6. 分析結果の取得とパース
        print("===== Gemini API 分析結果 (テキスト) =====")
        result_text = response.text
        print(result_text)

        analysis_result = {}
        for line in result_text.splitlines():
            line = line.strip()
            if line.startswith("Helmet:"):
                analysis_result["Helmet"] = line.replace("Helmet:", "").strip()
            elif line.startswith("Hair:"):
                analysis_result["Hair"] = line.replace("Hair:", "").strip()
            elif line.startswith("WorkClothes:"):
                analysis_result["WorkClothes"] = line.replace("WorkClothes:", "").strip()
            elif line.startswith("SafetyVest:"):
                analysis_result["SafetyVest"] = line.replace("SafetyVest:", "").strip()

        if not analysis_result:
            analysis_result = {
                "Helmet": "UNCERTAIN",
                "Hair": "UNCERTAIN",
                "WorkClothes": "UNCERTAIN",
                "SafetyVest": "UNCERTAIN",
            }
        else:
            analysis_result.setdefault("Helmet", "UNCERTAIN")
            analysis_result.setdefault("Hair", "UNCERTAIN")
            analysis_result.setdefault("WorkClothes", "UNCERTAIN")
            analysis_result.setdefault("SafetyVest", "UNCERTAIN")

        analysis_result_json_str = json.dumps(analysis_result, ensure_ascii=False)
        print("===== Gemini API 分析結果 (JSON) =====")
        print(analysis_result_json_str)

        # 7. BigQuery への書き込み
        client = bigquery.Client(project=project_id)
        dataset_id = "dataset"          # 例: "analysis_dataset"
        table_id = "analysis_results"   # 例: "analysis_results"
        table_ref = f"{project_id}.{dataset_id}.{table_id}"

        rows_to_insert = [
            {
                "file_name": file_name,
                "helmet": analysis_result.get("Helmet", "UNCERTAIN"),
                "hair": analysis_result.get("Hair", "UNCERTAIN"),
                "work_clothes": analysis_result.get("WorkClothes", "UNCERTAIN"),
                "safety_vest": analysis_result.get("SafetyVest", "UNCERTAIN"),
            }
        ]

        errors = client.insert_rows_json(table_ref, rows_to_insert)
        if not errors:
            print(f"BigQueryへの書き込みに成功しました: {table_ref}")
        else:
            print(f"BigQueryへの書き込みに失敗しました: {errors}")

        # 8. Slack 通知の準備と送信
        print("Slack 通知の準備")
        # 各項目ごとに「YES」でない場合にNG項目としてリストアップ
        items = {
            "Helmet": "ヘルメット",
            "Hair": "髪の毛",
            "WorkClothes": "作業着",
            "SafetyVest": "安全ベスト"
        }
        ng_items = []
        for key, description in items.items():
            if analysis_result.get(key, "UNCERTAIN") != "YES":
                ng_items.append(description)
        
        if not ng_items:
            subject = "[OK] 作業者装備自動点検通知"
            body = "素晴らしいです！\n本日も作業を安全に行ってください！"
        else:
            subject = "[NG] 作業者装備自動点検通知"
            body = "以下の項目について確認が必要です：\n\n"
            for idx, item in enumerate(ng_items, start=1):
                body += f"{idx}. {item}\n"
            body += "\n安全第一で作業をお願いします！"

        send_slack_notification(subject, body)

        return {"result": analysis_result}

    except Exception as e:
        error_message = f"エラーが発生しました: {str(e)}"
        print(error_message)
        return {"error": error_message}, 500
