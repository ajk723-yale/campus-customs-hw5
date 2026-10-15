# Design

## Layout

**What I chose:** I chose a clean, modern operations dashboard with a three-column layout:
- Left: Ticket cards showing each ticket's details, status, and next actions.
- Center: The selected ticket's details, agent activities, collaboration flow, and results.
- Right: Human approval requests and the checking balance.

**Why I chose it:** It allows managers to monitor operations and make decisions on one screen without switching between multiple pages.

## How Agents Read Differently

**What I chose:** I gave each of the five agents a distinctive cartoon-style character with its own color and appearance reflecting its role:
- Boss: A suit and tie.
- Inventory: A beanie and a box.
- Accounting: Glasses and a pencil.
- Facilities: A hard hat and overalls.
- Customer Service: A headset.

I also chose different facial expressions and animations to represent each agent's current state.

**Why I chose it:** I wanted managers to easily recognize which agent is responsible for each activity. I also wanted the agents to feel like a team of coworkers rather than separate AI components, making the dashboard more approachable and engaging.

## Agent Activities and Collaboration

**What I chose:** I chose an activity timeline that displays agent messages, delegations, and MCP tool usage. I also added short activity summaries with expandable details for individual tool calls and results. In addition, I chose a visual collaboration flow that shows how agents delegate tasks to one another, such as Boss → Facilities → Accounting. Agent activities are updated while the team is running.

**Why I chose it:** I wanted managers to understand both what each agent did and how the agents worked together. I chose expandable details because displaying every tool call at once would make the dashboard difficult to read. I also wanted to make the multi-agent process more intuitive and engaging by visualizing delegation rather than relying only on text logs.

## Ticket Status and Next Actions

**What I chose:** I chose to display each ticket's status clearly on its card and highlight the next action and remaining tasks near the top of the selected ticket's panel.
I also distinguished between a completed agent run and a genuinely resolved ticket. A ticket remains open if additional actions are still needed.

**Why I chose it:** Finishing an AI task doesn’t necessarily mean that the underlying business issue has been resolved. I wanna managers to focus on actual business outcomes.

## Human Approvals and Cash

**What I chose:** I placed human approval requests and the checking balance in the right column.
For payment requests, I chose to display both the current checking balance and the projected balance after the payment. I also separated purchase approvals from payment approvals and made clear that approving a purchase does not immediately change cash or inventory.

**Why I chose it:** The shop has limited cash and approving one payment could affect its ability to make other payments. I wanted to avoid confusion between actual cash movements and purchase approvals.

## Creative Choices and User Experience

**What I chose:** I added three creative elements to make the dashboard more enjoyable to use:
- Friendly cartoon characters with distinct appearances, facial expressions, and subtle animations that reflect each agent's activity.
- A visual collaboration flow that shows how agents delegate tasks and interact with one another.
- A small celebration with confetti, character reactions, and a visual highlight when a ticket is genuinely resolved.

I also chose to keep the animations subtle and respect reduced-motion settings.

**Why I chose it:** I wanted to make the dashboard feel like managing a small team of AI coworkers rather than simply operating a traditional business management system.
Also, animated characters make the agents more approachable and help managers recognize their current activities. The collaboration flow makes teamwork easier to understand and more interesting to watch. Finally, I wanted managers to feel a sense of accomplishment when a business issue is resolved and the dashboard still needs to be professional and comfortable for daily use.
