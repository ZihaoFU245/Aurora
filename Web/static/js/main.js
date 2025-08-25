document.addEventListener("DOMContentLoaded", () => {
    const chatBox = document.getElementById("chat-box");
    const userInput = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const chatListEl = document.getElementById("chat-list");
    const newChatBtn = document.getElementById("new-chat-btn");

    let currentChatId = null;
    let fullHistory = []; // full serialized history from server
    let typingEl = null;
    let loadingChats = false;

    const scrollToBottom = () => { chatBox.scrollTop = chatBox.scrollHeight; };
    const sanitize = (html) => DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });

    const renderMarkdownTo = (container, text) => {
        try {
            const raw = marked.parse(text ?? "");
            container.innerHTML = sanitize(raw);
            container.querySelectorAll('pre code').forEach(el => { try { hljs.highlightElement(el); } catch(_){} });
        } catch { container.textContent = text ?? ""; }
    };

    const addDeleteControl = (wrapper, indexInHistory) => {
        const btn = document.createElement('button');
        btn.className = 'delete-tail';
        btn.textContent = 'Delete';
        btn.title = 'Delete this message and the following';
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            // Truncate server chat
            try {
                const keep = indexInHistory; // keep all before this fullHistory index
                if (!currentChatId) return;
                const resp = await fetch(`/chats/${currentChatId}/truncate`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ keep }) });
                if (!resp.ok) throw new Error('Failed to truncate');
                const data = await resp.json();
                fullHistory = data.messages || [];
                renderHistory();
                refreshChatList();
            } catch(err) { console.error(err); }
        });
        wrapper.querySelector('.bubble').appendChild(btn);
    };

    const makeMessage = (sender, content, isMarkdown = true, index=null) => {
        const wrapper = document.createElement("div");
        wrapper.className = `message ${sender}`;

        const avatar = document.createElement("div");
        avatar.className = `avatar ${sender}`;
        avatar.textContent = sender === 'user' ? 'U' : 'A';

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        if (isMarkdown) renderMarkdownTo(bubble, content); else bubble.innerHTML = sanitize(String(content||'').replace(/\n/g,'<br>'));

        wrapper.appendChild(avatar); wrapper.appendChild(bubble);
        chatBox.appendChild(wrapper);
        if (index !== null) addDeleteControl(wrapper, index);
        scrollToBottom();
        return wrapper;
    };

    const addTyping = () => {
        removeTyping();
        typingEl = document.createElement('div');
        typingEl.className='message assistant';
        const avatar=document.createElement('div');
        avatar.className='avatar typing';
        avatar.textContent='…';
        const bubble=document.createElement('div');
        bubble.className='bubble typing-bubble';
        bubble.innerHTML='<span class="typing-dots" aria-label="Assistant is typing"></span>';
        typingEl.appendChild(avatar);
        typingEl.appendChild(bubble);
        chatBox.appendChild(typingEl);
        scrollToBottom();
    };
    const removeTyping = () => { if (typingEl?.parentElement) typingEl.parentElement.removeChild(typingEl); typingEl=null; };
    const setSending = (s) => { sendBtn.disabled = s; };
    const autosize = () => { userInput.style.height='auto'; const max=parseInt(getComputedStyle(userInput).maxHeight)||160; userInput.style.height=Math.min(userInput.scrollHeight,max)+'px'; };

    const renderHistory = () => {
        chatBox.innerHTML='';
        fullHistory.forEach((m,i) => {
            // Skip system and tool messages entirely in UI
            if (m.type === 'system' || m.type === 'tool') return;
            // Some AI messages are just tool-call placeholders with no textual content; hide them
            if (m.type === 'ai' && (!m.content || String(m.content).trim() === '')) return;
            const wrapper = makeMessage(m.type === 'human' ? 'user':'assistant', m.content, m.type === 'ai', i);
            wrapper.dataset.historyIndex = String(i);
        });
        scrollToBottom();
    };

    const sendMessage = async () => {
        const text = (userInput.value||'').trim(); if (!text) return;
        userInput.value=''; autosize(); setSending(true); addTyping();
        try {
            const resp = await fetch('/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ text, chat_id: currentChatId }) });
            if (!resp.ok) throw new Error('Network error');
            const data = await resp.json();
            currentChatId = data.chat_id;
            // Append delta to history
            if (data.history_delta) fullHistory = fullHistory.concat(data.history_delta);
            removeTyping();
            renderHistory();
            refreshChatList();
        } catch(err) {
            console.error(err); removeTyping(); makeMessage('assistant','Request failed, please retry later.', false); }
        finally { setSending(false); userInput.focus(); }
    };

    const refreshChatList = async () => {
        if (loadingChats) return; loadingChats = true;
        try {
            const r = await fetch('/chats'); if (!r.ok) throw new Error('list failed');
            const items = await r.json();
            chatListEl.innerHTML='';
            items.forEach(item => {
                const li = document.createElement('li');
                li.dataset.id = item.id;
                li.textContent = item.title || item.id;
                const count = document.createElement('span'); count.className='count'; count.textContent = item.message_count;
                li.appendChild(count);
                if (item.id === currentChatId) li.classList.add('active');
                li.addEventListener('click', () => loadChat(item.id));
                chatListEl.appendChild(li);
            });
        } catch(err){ console.error(err); }
        finally { loadingChats=false; }
    };

    const loadChat = async (id) => {
        try {
            const r = await fetch(`/chats/${id}`); if (!r.ok) throw new Error('load failed');
            const data = await r.json();
            currentChatId = data.id; fullHistory = data.messages || []; renderHistory(); refreshChatList();
        } catch(err){ console.error(err); }
    };

    const createNewChat = async () => {
        try {
            const r = await fetch('/chats', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) });
            if (!r.ok) throw new Error('create failed');
            const data = await r.json();
            currentChatId = data.id; fullHistory = []; renderHistory(); refreshChatList(); userInput.focus();
        } catch(err){ console.error(err); }
    };

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', e => { if (e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); }});
    userInput.addEventListener('input', autosize);
    newChatBtn.addEventListener('click', createNewChat);

    // Initial
    autosize(); userInput.focus();
    refreshChatList();
});