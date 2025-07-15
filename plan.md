# Plan

- [x] **Refine Agent Communication**: Modify the agent's output to be less verbose. The agent should send a single confirmation message and then work in the background.
- [x] **Implement Terminal Log Streaming**: Route PTY output from shell commands to the frontend terminal pane.
- [ ] **Enable Live App Preview**: Serve the Next.js application and display it in the live preview pane.
- [ ] **Test End-to-End Flow**: Verify the agent can handle the "make me a hello world app" request with the new UI features.
- [ ] **Address Technical Debt**: Resolve warnings related to Pydantic, LangChain deprecations, and other issues from the logs.
