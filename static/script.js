document.addEventListener('DOMContentLoaded', () => {
    const diaryInput = document.getElementById('diary-input');
    const saveDiaryBtn = document.getElementById('save-diary-btn');
    const diaryEntries = document.getElementById('diary-entries');
    const toastMessage = document.getElementById('toast-message');
    const promptInput = document.getElementById('prompt-input');
    const sendPromptBtn = document.getElementById('send-prompt-btn');
    const chatWindow = document.getElementById('chat-window');
    const loadingIndicator = document.getElementById('loading-indicator');
    // const API_KEY = ""; // NOTE: Leave this empty. The environment will provide it.
    const API_KEY = "AIzaSyAqxXH-nG3F3ktqRormFJN1PSYSxLH_Pvk"; // NOTE: Leave this empty. The environment will provide it.
    const API_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key=${API_KEY}`;
    // --- Data Management ---
    const getStoredData = (key) => {
        try {
            const data = localStorage.getItem(key);
            return data ? JSON.parse(data) : [];
        } catch (error) {
            console.error(`Error parsing ${key} from localStorage`, error);
            return [];
        }
    };
    const setStoredData = (key, data) => {
        localStorage.setItem(key, JSON.stringify(data));
    };
    // --- Diary Functions ---
    const renderDiaryEntries = () => {
        diaryEntries.innerHTML = '';
        const diaries = getStoredData('diaries');
        if (diaries.length === 0) {
            diaryEntries.innerHTML = '<p class="text-gray-500">まだ日記がありません。</p>';
            return;
        }
        diaries.sort((a, b) => new Date(b.date) - new Date(a.date)); // Newest first
        diaries.forEach(entry => {
            const entryEl = document.createElement('div');
            entryEl.className = 'bg-gray-50 p-4 rounded-lg border';
            const entryDate = new Date(entry.date).toLocaleString('ja-JP',
                { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            entryEl.innerHTML = `
                <p class="text-sm font-semibold text-gray-600">${entryDate}</p>
                <p class="mt-2 text-gray-800 whitespace-pre-wrap">${entry.content}</p>`;
            diaryEntries.appendChild(entryEl);
        });
    };
    saveDiaryBtn.addEventListener('click', () => {
        const content = diaryInput.value.trim();
        if (!content) return;
        const diaries = getStoredData('diaries');
        diaries.push({ date: new Date().toISOString(), content: content });
        setStoredData('diaries', diaries);
        diaryInput.value = '';
        renderDiaryEntries();
        // Show toast
        toastMessage.classList.remove('opacity-0');
        setTimeout(
            () => {
            toastMessage.classList.add('opacity-0');
        }, 2000);
    });
    // --- Chat Functions ---
    const addMessageToChat = (message, sender) => {
        const messageEl = document.createElement('div');
        messageEl.className = `chat-bubble ${sender === 'user' ? 'user-bubble' : 'ai-bubble'}`;
        // Sanitize and format the message to render newlines correctly
        messageEl.textContent = message;
        chatWindow.appendChild(messageEl);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };
    const renderChatHistory = () => {
        const chatHistory = getStoredData('chatHistory');
        chatHistory.forEach(msg => {
            addMessageToChat(msg.message, msg.sender);
        });
    };
    sendPromptBtn.addEventListener('click', handleSendPrompt);
    promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendPrompt();
        }
    });
    async function handleSendPrompt() {
        const promptText = promptInput.value.trim();
        if (!promptText) return;
        addMessageToChat(promptText, 'user');
        promptInput.value = '';
        promptInput.disabled = true;
        sendPromptBtn.disabled = true;
        loadingIndicator.classList.remove('hidden');
        loadingIndicator.classList.add('flex');
        try {
            // Save user message to history
            const chatHistory = getStoredData('chatHistory');
            chatHistory.push({ sender: 'user', message: promptText });
            setStoredData('chatHistory', chatHistory);
            // --- RAG Implementation ---
            const diaries = getStoredData('diaries');
            // Get recent 15 diaries
            const diaryContext = diaries.slice(-15).map(
                d => `日付: ${new Date(d.date).toLocaleDateString('ja-JP')}\n内容: ${d.content}`).join('\n\n');
            // Get recent 15 chat messages
            const chatContext = chatHistory.slice(-15).map(
                c => `${c.sender === 'user' ? 'ユーザー' : 'AI'}: ${c.message}`).join('\n');
            const systemPrompt = 
`あなたは、ユーザー自身のパーソナリティや話し方を理解しユーザー自身に成りきれるカウンセラーです。
以下の情報に基づいて、ユーザーに寄り添った、具体的で、ポジティブなアドバイスを提供してください。

# ユーザーの最近の日記
${diaryContext || "日記はまだありません。"}

# 最近の会話履歴
${chatContext}

# ルール
- 過去の日記や会話履歴から、ユーザーのパーソナリティを把握してください。
- 過去の日記や会話履歴から、ユーザーの価値観を把握してください。
- 過去の日記や会話履歴から、ユーザーの話し方を把握してください。
- ユーザー自身に成りきれるカウンセラーとして、把握したパーソナリティや価値観、話し方を反映した応答をしてください。
- あなたについて聞かれたときは、基本的にはユーザー自身であると回答してください。
- 対話を重視するために、一度に長い回答を返すことは避け、長くても200文字程度での回答を心がけてください。
- カウンセラーとしてユーザーの感情に寄り添い、共感を示してください。
- カウンセラーとして抽象的な一般論だけではなく、ユーザーの状況に特化したアドバイスを心がけてください。
- カウンセラーとしてユーザーを励まし、自己肯定感を高めるような、温かい言葉遣いをしてください。
- 応答は日本語でお願いします。`;

            const payload = {
                contents: [{ parts: [{ text: promptText }] }],
                systemInstruction: {
                    parts: [{ text: systemPrompt }]
                },
            };
            const response = await fetch(API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                throw new Error(`API error: ${response.statusText}`);
            }
            const result = await response.json();
            const aiResponse = result.candidates?.[0]?.content?.parts?.[0]?.text || "申し訳ありません、うまく応答を生成できませんでした。";
            addMessageToChat(aiResponse, 'ai');
            // Save AI response to history
            const updatedChatHistory = getStoredData('chatHistory');
            updatedChatHistory.push({ sender: 'ai', message: aiResponse });
            setStoredData('chatHistory', updatedChatHistory);
        } catch (error) {
            console.error('Error calling Gemini API:', error);
            addMessageToChat('エラーが発生しました。しばらくしてからもう一度お試しください。', 'ai');
            addMessageToChat(error, 'ai');
        } finally {
            promptInput.disabled = false;
            sendPromptBtn.disabled = false;
            loadingIndicator.classList.add('hidden');
            loadingIndicator.classList.remove('flex');
            promptInput.focus();
        }
    }
    // --- Initial Load ---
    function initializeApp() {
        renderDiaryEntries();
        renderChatHistory();
        // Clear the default welcome message if there is a history
        if (getStoredData('chatHistory').length > 0) {
            const initialMessage = chatWindow.querySelector('.ai-bubble');
            if (initialMessage && initialMessage.textContent.includes('こんにちは！')) {
                chatWindow.innerHTML = '';
                renderChatHistory();
            }
        }
    }
    initializeApp();
});
