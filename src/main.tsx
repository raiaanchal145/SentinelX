import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import App from "./App"
import { MockStoreProvider } from "./mocks/store"
import { ToastProvider } from "./components/ui/Toast"
import { MeProvider } from "./lib/me"
import "./index.css"

ReactDOM.createRoot(
  document.getElementById("root")!,
).render(
  <React.StrictMode>
    <BrowserRouter>
      <MockStoreProvider>
        <ToastProvider>
          <MeProvider>
            <App />
          </MeProvider>
        </ToastProvider>
      </MockStoreProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
