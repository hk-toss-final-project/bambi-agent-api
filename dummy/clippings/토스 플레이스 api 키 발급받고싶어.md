---
title: "토스 플레이스 api 키 발급받고싶어"
source: "https://www.perplexity.ai/search/2126347d-f9ed-431f-8ee8-92033f3831e2"
author:
published:
created: 2026-07-15
description: "Perplexity is a free AI-powered answer engine that provides accurate, trusted, and real-time answers to any question."
tags:
  - "clippings"
---
"토스 플레이스 API"로 검색했을 때 명확한 API 키 발급 방법이 나오지 않았습니다. 아마 다음 중 하나일 것 같아요:

1. **토스페이먼츠 (결제) API** 를 찾으시는 경우
2. **토스플레이스 (POS 단말기)** 의 개발자 연동을 찾으시는 경우
3. **Google Places API** 와 혼동하셨을 가능성

가장 일반적인 경우인 **토스페이먼츠 결제 API 키** 발급 방법을 알려드릴게요:

## 토스페이먼츠 API 키 발급 방법docs.tosspayments+1

1. **개발자센터 가입**
	- URL: https://developers.tosspayments.com [developers.tosspayments](https://developers.tosspayments.com/)
		- 이메일 주소만으로 회원가입 가능 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
2. **전자결제 신청** (실제 결제 연동 시)
	- 신청 전에는 개발 연동 체험 상점의 **테스트 키** 만 확인 가능 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
		- 테스트 키: 실제 결제가 일어나지 않아 개발 연동 시 유용 [tosspayments](https://www.tosspayments.com/blog/articles/29831)
3. **API 키 확인**
	- 상점관리자 → 좌측 하단 **개발자 센터** 클릭 [tosspayments](https://www.tosspayments.com/blog/articles/29831)
		- 개발자센터 좌측 메뉴 → **API 키** 메뉴 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
		- 클라이언트 키 (SDK 초기화) 와 시크릿 키 (API 호출) 복사 [docs.tosspayments](https://docs.tosspayments.com/reference/using-api/api-keys)
4. **테스트 키 예시** (사업자 등록 전 사용 가능) [inflearn](https://www.inflearn.com/community/questions/1253630/%ED%86%A0%EC%8A%A4-%ED%8E%98%EC%9D%B4%EB%A8%BC%EC%B8%A0-%EA%B2%B0%EC%A0%9C%EC%9C%84%EC%A0%AF-%EC%97%B0%EB%8F%99-api-%ED%82%A4-%EB%B9%84%ED%99%9C%EC%84%B1%ED%99%94)
	```
	text
	clientKey: test_gck_docs_Ovk5rk1EwkEbP0W43n07xlzm
	secretKey: test_gsk_docs_OaPz8L5KdmQXkzRz3y47BMw6
	```

---

혹시 찾으시는 것이 **토스플레이스 (POS 단말기)** 의 특정 API라면, [https://tossplace.com/sector/plugin](https://tossplace.com/sector/plugin) 에서 개발 연동 가이드를 다운로드하거나 담당자와 연락해야 할 것 같아요.[tossplace](https://tossplace.com/sector/plugin)

어떤 API를 연동하려는 건가요? (예: 결제, POS 단말기 연동, 다른 서비스)

후속 조치

검색Computer

모델