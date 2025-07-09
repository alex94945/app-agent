module.exports = {

"[externals]/next/dist/compiled/next-server/app-page-turbo.runtime.dev.js [external] (next/dist/compiled/next-server/app-page-turbo.runtime.dev.js, cjs)": (function(__turbopack_context__) {

var { g: global, __dirname, m: module, e: exports } = __turbopack_context__;
{
const mod = __turbopack_context__.x("next/dist/compiled/next-server/app-page-turbo.runtime.dev.js", () => require("next/dist/compiled/next-server/app-page-turbo.runtime.dev.js"));

module.exports = mod;
}}),
"[project]/src/app/components/ChatInterface.tsx [app-ssr] (ecmascript)": ((__turbopack_context__) => {
"use strict";

var { g: global, __dirname } = __turbopack_context__;
{
__turbopack_context__.s({
    "default": (()=>ChatInterface)
});
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
'use client';
;
;
function ChatInterface() {
    const [socket, setSocket] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [input, setInput] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])('');
    const [messages, setMessages] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])([]);
    const [isConnected, setIsConnected] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        // Assuming the gateway runs on port 8001
        const ws = new WebSocket('ws://localhost:8001/api/agent');
        ws.onopen = ()=>{
            console.log('WebSocket connected');
            setIsConnected(true);
            setMessages([
                {
                    source: 'system',
                    content: 'Connected to agent.',
                    type: 'text'
                }
            ]);
        };
        ws.onmessage = (event)=>{
            try {
                const message = JSON.parse(event.data);
                handleIncomingMessage(message);
            } catch (error) {
                console.error('Failed to parse incoming message:', event.data);
                setMessages((prev)=>[
                        ...prev,
                        {
                            source: 'system',
                            content: 'Received malformed message.',
                            type: 'error'
                        }
                    ]);
            }
        };
        ws.onclose = ()=>{
            console.log('WebSocket disconnected');
            setIsConnected(false);
            setMessages((prev)=>[
                    ...prev,
                    {
                        source: 'system',
                        content: 'Connection lost.',
                        type: 'error'
                    }
                ]);
        };
        ws.onerror = (error)=>{
            console.error('WebSocket error:', error);
            setMessages((prev)=>[
                    ...prev,
                    {
                        source: 'system',
                        content: 'Connection error.',
                        type: 'error'
                    }
                ]);
        };
        setSocket(ws);
        // Clean up the connection when the component unmounts
        return ()=>{
            ws.close();
        };
    }, []);
    const handleIncomingMessage = (msg)=>{
        let displayMsg = null;
        switch(msg.t){
            case 'tok':
                // Append token to the last message if it's from the agent
                setMessages((prev)=>{
                    const lastMsg = prev[prev.length - 1];
                    if (lastMsg && lastMsg.source === 'agent') {
                        return [
                            ...prev.slice(0, -1),
                            {
                                ...lastMsg,
                                content: lastMsg.content + msg.d
                            }
                        ];
                    }
                    return [
                        ...prev,
                        {
                            source: 'agent',
                            content: msg.d,
                            type: 'text'
                        }
                    ];
                });
                break;
            case 'agent_response':
                displayMsg = {
                    source: 'agent',
                    content: msg.d,
                    type: 'text'
                };
                break;
            case 'tool_call':
                displayMsg = {
                    source: 'tool',
                    content: `Calling: ${msg.d.name}(${JSON.stringify(msg.d.args)})`,
                    type: 'tool_call'
                };
                break;
            case 'tool_result':
                displayMsg = {
                    source: 'tool',
                    content: `Result from ${msg.d.tool_name}: ${JSON.stringify(msg.d.result)}`,
                    type: 'tool_result'
                };
                break;
            case 'final':
                displayMsg = {
                    source: 'agent',
                    content: msg.d,
                    type: 'text'
                };
                break;
            case 'error':
                displayMsg = {
                    source: 'system',
                    content: msg.d,
                    type: 'error'
                };
                break;
        }
        if (displayMsg) {
            setMessages((prev)=>[
                    ...prev,
                    displayMsg
                ]);
        }
    };
    const handleSubmit = (e)=>{
        e.preventDefault();
        if (input.trim() && socket && isConnected) {
            const messageToSend = {
                prompt: input
            };
            socket.send(JSON.stringify(messageToSend));
            setMessages((prev)=>[
                    ...prev,
                    {
                        source: 'user',
                        content: input,
                        type: 'text'
                    }
                ]);
            setInput('');
        }
    };
    const getMessageStyle = (source)=>{
        switch(source){
            case 'user':
                return 'bg-blue-100 dark:bg-blue-900 self-end';
            case 'agent':
                return 'bg-gray-200 dark:bg-gray-700 self-start';
            case 'tool':
                return 'bg-yellow-100 dark:bg-yellow-800 text-xs italic self-start';
            case 'system':
                return 'bg-red-100 dark:bg-red-900 text-xs text-center self-center';
            default:
                return 'bg-white dark:bg-gray-800';
        }
    };
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "flex flex-col w-1/3 max-w-md border-r border-gray-200 dark:border-gray-800 h-full",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "flex-1 p-4 overflow-y-auto flex flex-col gap-3",
                children: messages.map((msg, index)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: `p-2 rounded-lg max-w-xs ${getMessageStyle(msg.source)}`,
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                            className: "whitespace-pre-wrap",
                            children: msg.content
                        }, void 0, false, {
                            fileName: "[project]/src/app/components/ChatInterface.tsx",
                            lineNumber: 117,
                            columnNumber: 13
                        }, this)
                    }, index, false, {
                        fileName: "[project]/src/app/components/ChatInterface.tsx",
                        lineNumber: 116,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/src/app/components/ChatInterface.tsx",
                lineNumber: 114,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-4 border-t border-gray-200 dark:border-gray-800",
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("form", {
                    className: "flex gap-2",
                    onSubmit: handleSubmit,
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            type: "text",
                            placeholder: isConnected ? 'Type your message...' : 'Connecting...',
                            value: input,
                            onChange: (e)=>setInput(e.target.value),
                            className: "flex-1 p-2 border rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-white",
                            disabled: !isConnected
                        }, void 0, false, {
                            fileName: "[project]/src/app/components/ChatInterface.tsx",
                            lineNumber: 123,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            type: "submit",
                            className: "px-4 py-2 font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:bg-gray-500",
                            disabled: !isConnected,
                            children: "Send"
                        }, void 0, false, {
                            fileName: "[project]/src/app/components/ChatInterface.tsx",
                            lineNumber: 131,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/src/app/components/ChatInterface.tsx",
                    lineNumber: 122,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/src/app/components/ChatInterface.tsx",
                lineNumber: 121,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/app/components/ChatInterface.tsx",
        lineNumber: 113,
        columnNumber: 5
    }, this);
}
}}),
"[project]/node_modules/next/dist/server/route-modules/app-page/module.compiled.js [app-ssr] (ecmascript)": (function(__turbopack_context__) {

var { g: global, __dirname, m: module, e: exports } = __turbopack_context__;
{
"use strict";
if ("TURBOPACK compile-time falsy", 0) {
    "TURBOPACK unreachable";
} else {
    if ("TURBOPACK compile-time falsy", 0) {
        "TURBOPACK unreachable";
    } else {
        if ("TURBOPACK compile-time truthy", 1) {
            if ("TURBOPACK compile-time truthy", 1) {
                module.exports = __turbopack_context__.r("[externals]/next/dist/compiled/next-server/app-page-turbo.runtime.dev.js [external] (next/dist/compiled/next-server/app-page-turbo.runtime.dev.js, cjs)");
            } else {
                "TURBOPACK unreachable";
            }
        } else {
            "TURBOPACK unreachable";
        }
    }
} //# sourceMappingURL=module.compiled.js.map
}}),
"[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)": (function(__turbopack_context__) {

var { g: global, __dirname, m: module, e: exports } = __turbopack_context__;
{
"use strict";
module.exports = __turbopack_context__.r("[project]/node_modules/next/dist/server/route-modules/app-page/module.compiled.js [app-ssr] (ecmascript)").vendored['react-ssr'].ReactJsxDevRuntime; //# sourceMappingURL=react-jsx-dev-runtime.js.map
}}),
"[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)": (function(__turbopack_context__) {

var { g: global, __dirname, m: module, e: exports } = __turbopack_context__;
{
"use strict";
module.exports = __turbopack_context__.r("[project]/node_modules/next/dist/server/route-modules/app-page/module.compiled.js [app-ssr] (ecmascript)").vendored['react-ssr'].React; //# sourceMappingURL=react.js.map
}}),

};

//# sourceMappingURL=%5Broot-of-the-server%5D__c44ff3fc._.js.map