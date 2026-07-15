---
title: "DDD 아키텍처의 의존성 도식"
source: "https://claude.ai/chat/c29532f0-2fe7-4913-853a-1bb009bb7fca"
author:
published:
created: 2026-07-15
description: "Claude conversation with 6 messages"
tags:
  - "clippings"
---
**You**

DDD 아키텍쳐에서 의존에 관한 내용을 도식으로 설명해줘.

---

**Claude**

DDD(Domain-Driven Design) 아키텍처의 의존성 구조를 도식으로 설명해드리겠습니다.

---

**You**

그럼 모듈 내에서 A 모듈이 B 모듈에 의존할 때 어떤 계층에서 의존 해야하나?

---

**Claude**

DDD에서 모듈 간 의존성은 **Application Layer** 에서 처리하는 것이 원칙입니다. 도식으로 설명해드리겠습니다.

---

**You**

그럼 application 계층에 있는 dto간 의존 관계가 발생한 경우 각 모듈이 의존하면 강한 결합이 발생하게 되는데 이게 좋은 아키텍쳐인가 아닌가?

---

**Claude**

좋은 질문입니다! DTO 간 의존으로 인한 강한 결합은 **좋지 않은 아키텍처** 입니다. 더 나은 방법들을 도식으로 설명해드리겠습니다.