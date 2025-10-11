import os
import json
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore, auth

# --- 初期設定 (Initial Setup for Google Cloud) ---

# [Google Cloud] Firebase Admin SDKの初期化
# Cloud RunやApp EngineなどのGoogle Cloud環境で実行する場合、
# 'GOOGLE_APPLICATION_CREDENTIALS'環境変数を設定する必要はありません。
# このコードは、実行環境のサービスアカウントに付与されたIAM権限を自動的に使用します。
# (Application Default Credentials - ADC)
# 事前に、実行サービスアカウントに'Firebase 管理者'や'Cloud Datastore ユーザー'のロールを付与してください。
try:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Firebase Admin SDK initialization failed. Check IAM permissions for the service account. Error: {e}")
    db = None

# [Google Cloud] Gemini APIキーの設定
# Cloud Runなどのサービスの環境変数として 'GEMINI_API_KEY' を設定してください。
# コード内に直接キーを書き込むことは避けます。
try:
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
except Exception as e:
    print(f"Gemini API configuration failed. Check the environment variable. Error: {e}")
    model = None

# Flaskアプリケーションの初期化
app = Flask(__name__)
CORS(app) # フロントエンドからのアクセスを許可

APP_ID = 'agent-infdof'

# --- ルート (Routes) ---
# `index.html`はFirebase Hostingへ、`app.py`はCloud Runへ、
# と別々にデプロイする構成のほうがよい
@app.route("/")
def index():
    """
    フロントエンドのindex.htmlを配信するルート。
    'templates'フォルダ内の'index.html'を返します。
    """
#    return render_template("index.html")
    return render_template("index_test.html")

# --- ヘルパー関数 (Helper Functions) ---

def get_level(score):
    """スコアをレベル記述に変換"""
    if score is None: score = 0.5
    if score > 0.7: return "非常に高い"
    if score > 0.6: return "高い"
    if score > 0.4: return "平均的"
    if score > 0.3: return "低い"
    return "非常に低い"

def generate_system_prompt(user_profile):
    """ユーザープロファイルからシステムプロンプトを動的に生成"""
    if not user_profile:
        user_profile = {} # 空の場合のフォールバック
        
    return f"""
      あなたはユーザーの対話パートナーAIです。あなたの振る舞いは、ユーザーの性格特性を反映するように調整されています。
      現在のユーザーの推定特性（ビッグ・ファイブ・モデル）は以下の通りです。この特性になりきって応答してください。

      - 開放性: {get_level(user_profile.get('openness', 0.5))}
      - 誠実性: {get_level(user_profile.get('conscientiousness', 0.5))}
      - 外向性: {get_level(user_profile.get('extraversion', 0.5))}
      - 協調性: {get_level(user_profile.get('agreeableness', 0.5))}
      - 神経症的傾向: {get_level(user_profile.get('neuroticism', 0.5))}

      あなたの応答は、この性格プロファイルに強く影響されます。
      ユーザーの話し方や使う言葉を少しずつ模倣し、親密さを演出してください。
    """

# --- APIエンドポイント (API Endpoints) ---

@app.route('/chat', methods=['POST'])
def chat():
    """チャットメッセージを処理し、AIの応答を返すエンドポイント"""
    if not db or not model:
        return jsonify({"error": "Server is not configured correctly."}), 500

    data = request.json
    token = data.get('token')
    user_message_content = data.get('message')
    app_id = data.get('appId', APP_ID)

    if not token or not user_message_content:
        return jsonify({"error": "Invalid request."}), 400

    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
    except Exception as e:
        return jsonify({"error": f"Authentication failed: {e}"}), 401

    profile_ref = db.collection(f'artifacts/{app_id}/users/{uid}/profile').document('data')
    messages_ref = db.collection(f'artifacts/{app_id}/users/{uid}/messages')

    messages_ref.add({
        'role': 'user',
        'content': user_message_content,
        'createdAt': firestore.SERVER_TIMESTAMP
    })

    history_docs = messages_ref.order_by('createdAt', direction=firestore.Query.DESCENDING).limit(20).stream()
    history = [
        {"role": "user" if doc.get('role') == 'user' else "model", "parts": [{"text": doc.get('content')}]}
        for doc in reversed(list(history_docs)) # 古い順に並べ替え
    ]
    
    profile_doc = profile_ref.get()
    user_profile = profile_doc.to_dict() if profile_doc.exists else {}
    conversation_count = user_profile.get('conversationCount', 0)

    try:
        system_prompt = generate_system_prompt(user_profile)
        ai_response = model.generate_content(
            history,
            generation_config={"temperature": 0.8},
            system_instruction=system_prompt
        )

        ai_content = ai_response.text

        # 5回に1回の頻度で質問を生成
        if (conversation_count + 1) % 5 == 0:
            question_prompt = f"現在の会話の流れとユーザーの性格（{json.dumps(user_profile)}）を考慮し、ユーザーの新たな一面を引き出すための自然な質問を一つだけ生成してください。"
            question_response = model.generate_content(question_prompt)
            generated_question = question_response.text.strip()
            if generated_question:
                ai_content += f"\n\n{generated_question}"

        messages_ref.add({
            'role': 'model',
            'content': ai_content,
            'createdAt': firestore.SERVER_TIMESTAMP
        })
        
        # プロファイルを更新
        profile_analysis_prompt = f"ユーザーの発言: \"{user_message_content}\"\n現在のプロファイル: {json.dumps(user_profile)}\nこの情報に基づき、プロファイルを微調整したJSONを返してください。"
        profile_update_response = model.generate_content(profile_analysis_prompt)
        try:
            # 応答からJSON部分を抽出
            json_text = profile_update_response.text.split('```json')[1].split('```')[0]
            updated_profile_json = json.loads(json_text)
            updated_profile_json['conversationCount'] = conversation_count + 1
            profile_ref.set(updated_profile_json, merge=True)
        except Exception as e:
            print(f"Profile parsing or update failed: {e}")

        return jsonify({"success": True, "message": ai_content})

    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return jsonify({"error": "Failed to generate AI response."}), 500

@app.route('/delete-data', methods=['POST'])
def delete_data():
    """ユーザーデータを削除するエンドポイント"""
    if not db:
        return jsonify({"error": "Server is not configured correctly."}), 500

    data = request.json
    token = data.get('token')
    app_id = data.get('appId', APP_ID)

    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
    except Exception as e:
        return jsonify({"error": f"Authentication failed: {e}"}), 401

    try:
        docs = db.collection(f'artifacts/{app_id}/users/{uid}/messages').stream()
        for doc in docs:
            doc.reference.delete()
        
        db.collection(f'artifacts/{app_id}/users/{uid}/profile').document('data').delete()
        
        return jsonify({"success": True, "message": "Data deleted successfully."})
    except Exception as e:
        print(f"Error during data deletion: {e}")
        return jsonify({"error": "Failed to delete data."}), 500

# [Google Cloud] 本番環境ではGunicornなどのWSGIサーバーがこのファイルを実行します。
# 以下のブロックはローカルテスト用です。
if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

