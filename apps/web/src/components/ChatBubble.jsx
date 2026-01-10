import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import "./ChatBubble.css";

export default function ChatBubble({ sender, text }) {
  const [copied, setCopied] = useState(false);
  const [codeCopied, setCodeCopied] = useState({});

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCodeCopy = (code, index) => {
    navigator.clipboard.writeText(code);
    setCodeCopied({ ...codeCopied, [index]: true });
    setTimeout(() => {
      setCodeCopied({ ...codeCopied, [index]: false });
    }, 2000);
  };

  let codeBlockIndex = 0;

  return (
    <div className={`chat-bubble ${sender === "user" ? "user" : "ai"}`}>
      <div className="bubble-content">
        <ReactMarkdown
          components={{
            code({ inline, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || "");
              const currentIndex = codeBlockIndex++;
              const codeString = String(children).replace(/\n$/, "");

              return !inline && match ? (
                <div className="code-block-wrapper">
                  <div className="code-block-header">
                    <span className="code-language">{match[1]}</span>
                    <button
                      className="code-copy-btn"
                      onClick={() => handleCodeCopy(codeString, currentIndex)}
                      type="button"
                    >
                      {codeCopied[currentIndex] ? "✓ Copied!" : "📋 Copy code"}
                    </button>
                  </div>
                  <SyntaxHighlighter
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                    {...props}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                </div>
              ) : (
                <code className={`inline-code ${className || ""}`} {...props}>
                  {children}
                </code>
              );
            },
          }}
        >
          {text}
        </ReactMarkdown>
      </div>

      {sender === "ai" && (
        <div className="bubble-actions">
          <button className="action-btn" onClick={handleCopy} type="button">
            {copied ? "✓ Copied!" : "📋 Copy response"}
          </button>
        </div>
      )}
    </div>
  );
}
