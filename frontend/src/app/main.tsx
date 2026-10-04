import { createRoot } from "react-dom/client";
import { Workbench } from "../pages/workbench";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing");
createRoot(root).render(<Workbench/>);
