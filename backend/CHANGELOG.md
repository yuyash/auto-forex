# Changelog

## [2.12.11](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.10...backend-v2.12.11) (2026-06-28)


### Bug Fixes

* **snowball:** sync pending weighted TP ([#851](https://github.com/yuyash/auto-forex-web-service/issues/851)) ([f573bae](https://github.com/yuyash/auto-forex-web-service/commit/f573bae4c862430fc9c62ebb1acb0fb436664c42))

## [2.12.10](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.9...backend-v2.12.10) (2026-06-28)


### Bug Fixes

* **snowball:** wait for profitable rebuild take profit ([#849](https://github.com/yuyash/auto-forex-web-service/issues/849)) ([5d543f7](https://github.com/yuyash/auto-forex-web-service/commit/5d543f7511be483ff04d0f9d6bff5e19458d736e))

## [2.12.9](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.8...backend-v2.12.9) (2026-06-25)


### Bug Fixes

* **strategy:** preserve snowball layer initial TP bounds ([#847](https://github.com/yuyash/auto-forex-web-service/issues/847)) ([26a6a44](https://github.com/yuyash/auto-forex-web-service/commit/26a6a441a4dc3eaf260f28eb69b35f73ba1bf9e1))

## [2.12.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.7...backend-v2.12.8) (2026-06-20)


### Bug Fixes

* **snowball:** block TP reentry while cycles are pending ([#844](https://github.com/yuyash/auto-forex-web-service/issues/844)) ([86e5703](https://github.com/yuyash/auto-forex-web-service/commit/86e5703095703337ec8ebd9ada6a2fd4ced368db))

## [2.12.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.6...backend-v2.12.7) (2026-06-19)


### Bug Fixes

* **security:** patch cryptography/Django CVEs and harden error output - Bump cryptography to &gt;=48.0.1 (GHSA-537c-gmf6-5ccf) and Django to &gt;=5.2.14 to clear Dependabot alerts [#108](https://github.com/yuyash/auto-forex-web-service/issues/108), [#85](https://github.com/yuyash/auto-forex-web-service/issues/85), [#86](https://github.com/yuyash/auto-forex-web-service/issues/86), [#87](https://github.com/yuyash/auto-forex-web-service/issues/87). - stream.py: reconstruct task_id through the UUID constructor so only a validated canonical value can reach the SSE response body, resolving reflective XSS alert [#102](https://github.com/yuyash/auto-forex-web-service/issues/102). - query_params.py: stop echoing the raw regex exception text to clients; log it server-side and return a generic message, resolving stack-trace exposure alert [#105](https://github.com/yuyash/auto-forex-web-service/issues/105). ([a9968d8](https://github.com/yuyash/auto-forex-web-service/commit/a9968d87d11a9759cf647d46169002daffbd7d88))
* **security:** patch cryptography/Django CVEs and harden error output ([#842](https://github.com/yuyash/auto-forex-web-service/issues/842)) ([a9968d8](https://github.com/yuyash/auto-forex-web-service/commit/a9968d87d11a9759cf647d46169002daffbd7d88))

## [2.12.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.5...backend-v2.12.6) (2026-06-19)


### Bug Fixes

* **snowball:** enforce rebuild stop-loss invariants ([#838](https://github.com/yuyash/auto-forex-web-service/issues/838)) ([ab25451](https://github.com/yuyash/auto-forex-web-service/commit/ab2545136e05b5444a80253785c90d8098488a26))

## [2.12.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.4...backend-v2.12.5) (2026-06-18)


### Bug Fixes

* **snowball:** resume multi-layer pending cycles instead of freezing ([#836](https://github.com/yuyash/auto-forex-web-service/issues/836)) ([bee13f7](https://github.com/yuyash/auto-forex-web-service/commit/bee13f74080a98bb7e819174ff663c666a0633fe))

## [2.12.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.3...backend-v2.12.4) (2026-06-18)


### Bug Fixes

* **snowball:** keep pending cycles averaging instead of freezing ([#833](https://github.com/yuyash/auto-forex-web-service/issues/833)) ([0661bb1](https://github.com/yuyash/auto-forex-web-service/commit/0661bb1ac912f8bd4b2fc0c399fbe5e8edc4af7d))

## [2.12.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.2...backend-v2.12.3) (2026-05-27)


### Bug Fixes

* **backtest:** prevent impossible simulated fills ([#830](https://github.com/yuyash/auto-forex-web-service/issues/830)) ([bd07ee1](https://github.com/yuyash/auto-forex-web-service/commit/bd07ee16459917b72ec1da7870a9aabe4e5222fe))
* batch raw backtest tick queries ([#829](https://github.com/yuyash/auto-forex-web-service/issues/829)) ([533d312](https://github.com/yuyash/auto-forex-web-service/commit/533d31209b4bf7a885ee1cb420ee6f719f9fdf41))
* **ci:** restart in-memory backtests during deploy ([#827](https://github.com/yuyash/auto-forex-web-service/issues/827)) ([8ad9bed](https://github.com/yuyash/auto-forex-web-service/commit/8ad9bed2d5b5a6593d6b684c126d76a37d2783d0))

## [2.12.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.1...backend-v2.12.2) (2026-05-27)


### Bug Fixes

* **snowball:** prevent stale warmup metrics ([#825](https://github.com/yuyash/auto-forex-web-service/issues/825)) ([6d430a1](https://github.com/yuyash/auto-forex-web-service/commit/6d430a17d12a625e9568e3659ff8a431f0c28065))

## [2.12.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.12.0...backend-v2.12.1) (2026-05-27)


### Bug Fixes

* **trading:** resolve snowball cycle ids after live fills ([#823](https://github.com/yuyash/auto-forex-web-service/issues/823)) ([54cbd12](https://github.com/yuyash/auto-forex-web-service/commit/54cbd121b89dd8af8ffee4f2fa24d44c3585f9b0))

## [2.12.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.11.0...backend-v2.12.0) (2026-05-26)


### Features

* **strategy:** add warmup max r setting ([#821](https://github.com/yuyash/auto-forex-web-service/issues/821)) ([e286a1a](https://github.com/yuyash/auto-forex-web-service/commit/e286a1ada17af991834b9ce86b0f9102a4f215ed))

## [2.11.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.10.1...backend-v2.11.0) (2026-05-25)


### Features

* **strategy:** add cycle rebuild guard ([#818](https://github.com/yuyash/auto-forex-web-service/issues/818)) ([41b4114](https://github.com/yuyash/auto-forex-web-service/commit/41b411429917cdf17e22966d8160977871164703))


### Bug Fixes

* **strategy:** resume rebuild guard at pending trigger ([#820](https://github.com/yuyash/auto-forex-web-service/issues/820)) ([78d0e20](https://github.com/yuyash/auto-forex-web-service/commit/78d0e20fbfe482170393754f624cbee9039a51dc))

## [2.10.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.10.0...backend-v2.10.1) (2026-05-24)


### Bug Fixes

* strict backtest close targets ([#816](https://github.com/yuyash/auto-forex-web-service/issues/816)) ([4e9edf7](https://github.com/yuyash/auto-forex-web-service/commit/4e9edf7c0357588cc030cde1f2654999e217bd52))

## [2.10.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.9.0...backend-v2.10.0) (2026-05-24)


### Features

* **strategy:** add snowball risk guards ([#811](https://github.com/yuyash/auto-forex-web-service/issues/811)) ([b955e1c](https://github.com/yuyash/auto-forex-web-service/commit/b955e1c8527a2faa1fa880c5605ea7e68800ff89))

## [2.9.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.8.1...backend-v2.9.0) (2026-05-24)


### Features

* **trading:** add task-scoped market events ([#809](https://github.com/yuyash/auto-forex-web-service/issues/809)) ([6c0efbe](https://github.com/yuyash/auto-forex-web-service/commit/6c0efbe1829d8de457343266e8a1fef125b08947))

## [2.8.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.8.0...backend-v2.8.1) (2026-05-23)


### Bug Fixes

* **api:** tolerate Redis throttle cache outages ([#807](https://github.com/yuyash/auto-forex-web-service/issues/807)) ([d3c4966](https://github.com/yuyash/auto-forex-web-service/commit/d3c49669afb7eef02c127bfff5c53d50b375f65d))

## [2.8.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.7.2...backend-v2.8.0) (2026-05-23)


### Features

* task stop reasons watermarks ([#804](https://github.com/yuyash/auto-forex-web-service/issues/804)) ([4b9eebb](https://github.com/yuyash/auto-forex-web-service/commit/4b9eebb6305b03391610ae314caaf0dc611534d6))

## [2.7.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.7.1...backend-v2.7.2) (2026-05-22)


### Bug Fixes

* **snowball:** keep auto base unit metrics fresh ([#802](https://github.com/yuyash/auto-forex-web-service/issues/802)) ([b495921](https://github.com/yuyash/auto-forex-web-service/commit/b49592190445b67814bf397a810141f3165d2c36))

## [2.7.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.7.0...backend-v2.7.1) (2026-05-22)


### Bug Fixes

* **metrics:** use wall-clock interval for tick rate ([#797](https://github.com/yuyash/auto-forex-web-service/issues/797)) ([67a824b](https://github.com/yuyash/auto-forex-web-service/commit/67a824bf7aee4007665bfc020aa43a8593940064))

## [2.7.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.6.0...backend-v2.7.0) (2026-05-22)


### Features

* **trading:** add tick granularity for live tasks ([#794](https://github.com/yuyash/auto-forex-web-service/issues/794)) ([1625104](https://github.com/yuyash/auto-forex-web-service/commit/1625104392db1c78ff815156a885718cf5b7a617))


### Bug Fixes

* task ticks per second window ([#796](https://github.com/yuyash/auto-forex-web-service/issues/796)) ([edb9915](https://github.com/yuyash/auto-forex-web-service/commit/edb991580c2e9f93f462743c3a08efdd75b7b7ab))

## [2.6.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.5.0...backend-v2.6.0) (2026-05-21)


### Features

* backtest closed datetime windows ([#792](https://github.com/yuyash/auto-forex-web-service/issues/792)) ([3df6cad](https://github.com/yuyash/auto-forex-web-service/commit/3df6cadf5e9ff0db57146768acdd4b35d7869e1c))

## [2.5.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.4.0...backend-v2.5.0) (2026-05-21)


### Features

* **backtest:** add tick quality filters ([#791](https://github.com/yuyash/auto-forex-web-service/issues/791)) ([a7e2c90](https://github.com/yuyash/auto-forex-web-service/commit/a7e2c90c52d9afc33dcacdff48b740969a02905f))


### Bug Fixes

* **backtest:** preserve pending in-memory rebuild cycles ([#789](https://github.com/yuyash/auto-forex-web-service/issues/789)) ([f1421ca](https://github.com/yuyash/auto-forex-web-service/commit/f1421ca3b36527acddff6f24048c6c72890c17d0))

## [2.4.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.3.0...backend-v2.4.0) (2026-05-20)


### Features

* **backtest:** add in-memory execution mode ([#788](https://github.com/yuyash/auto-forex-web-service/issues/788)) ([0663d61](https://github.com/yuyash/auto-forex-web-service/commit/0663d6198ba5f4dc3eeee71d6356962a51557779))


### Bug Fixes

* execution comparison labels ([#786](https://github.com/yuyash/auto-forex-web-service/issues/786)) ([ac1b843](https://github.com/yuyash/auto-forex-web-service/commit/ac1b84349fa83b0b0a2aa7d13717d67be7698794))

## [2.3.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.2.0...backend-v2.3.0) (2026-05-19)


### Features

* backtest holiday calendar ([#784](https://github.com/yuyash/auto-forex-web-service/issues/784)) ([60a3bbc](https://github.com/yuyash/auto-forex-web-service/commit/60a3bbc9b7e06d90d1ca9ef98d89ba9064759252))


### Bug Fixes

* **snowball:** anchor stop-loss-exit rebuild trigger on SL level and add buffer/cooldown ([#782](https://github.com/yuyash/auto-forex-web-service/issues/782)) ([cae0bc0](https://github.com/yuyash/auto-forex-web-service/commit/cae0bc0058ac0c916489e95fa691306224ab5374))

## [2.2.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.1.0...backend-v2.2.0) (2026-05-19)


### Features

* **strategy:** add snowball warmup controls ([#779](https://github.com/yuyash/auto-forex-web-service/issues/779)) ([3aac6bd](https://github.com/yuyash/auto-forex-web-service/commit/3aac6bdd46e4c57bf7e4eba6942e4d050e72658b))


### Bug Fixes

* **trading:** retry transient OANDA auth reads ([#780](https://github.com/yuyash/auto-forex-web-service/issues/780)) ([a3c16b0](https://github.com/yuyash/auto-forex-web-service/commit/a3c16b0aade83b2de951959944795cf093582e74))

## [2.1.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.7...backend-v2.1.0) (2026-05-19)


### Features

* **metrics:** show current base units ([#774](https://github.com/yuyash/auto-forex-web-service/issues/774)) ([e81bcb0](https://github.com/yuyash/auto-forex-web-service/commit/e81bcb0f1c33f38e434f4b6b375d2cf1a3eae274))


### Performance

* archive snowball completed cycles ([#772](https://github.com/yuyash/auto-forex-web-service/issues/772)) ([67f8a3b](https://github.com/yuyash/auto-forex-web-service/commit/67f8a3b6fb6b7c72aa159e101ae9ee31f9f80081))

## [2.0.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.6...backend-v2.0.7) (2026-05-18)


### Bug Fixes

* **strategy:** clear closed rebuilt grid slots ([#767](https://github.com/yuyash/auto-forex-web-service/issues/767)) ([95fe53f](https://github.com/yuyash/auto-forex-web-service/commit/95fe53f26c116c0aadcaadf370c7602a7d9537d6))
* **strategy:** reuse refillable snowball head slots ([6bfe278](https://github.com/yuyash/auto-forex-web-service/commit/6bfe2784028b57c63b1d16629dde06846102b8d9))

## [2.0.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.5...backend-v2.0.6) (2026-05-18)


### Bug Fixes

* **ui:** restore grid states and chart sizing ([#765](https://github.com/yuyash/auto-forex-web-service/issues/765)) ([30293a7](https://github.com/yuyash/auto-forex-web-service/commit/30293a78258fb82d77b1eecbd9307e986cb04334))

## [2.0.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.4...backend-v2.0.5) (2026-05-17)


### Bug Fixes

* **strategy:** persist snowball grid counts ([#763](https://github.com/yuyash/auto-forex-web-service/issues/763)) ([a912c03](https://github.com/yuyash/auto-forex-web-service/commit/a912c03b0798f816d9abb354e9103b4c3120c74f))

## [2.0.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.3...backend-v2.0.4) (2026-05-17)


### Bug Fixes

* **snowball:** expose counter layer controls ([#761](https://github.com/yuyash/auto-forex-web-service/issues/761)) ([58e93d5](https://github.com/yuyash/auto-forex-web-service/commit/58e93d5c782e761ad6001a2a209da6454a47b1c7))

## [2.0.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.2...backend-v2.0.3) (2026-05-17)


### Bug Fixes

* **strategy:** move snowball refill limit below reseed ([#759](https://github.com/yuyash/auto-forex-web-service/issues/759)) ([b9034a1](https://github.com/yuyash/auto-forex-web-service/commit/b9034a1d043502629c9705b26fe9d624fb9ef38b))

## [2.0.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.1...backend-v2.0.2) (2026-05-17)


### Bug Fixes

* snowball rebuild option order ([#757](https://github.com/yuyash/auto-forex-web-service/issues/757)) ([046a753](https://github.com/yuyash/auto-forex-web-service/commit/046a753c9196d4170c71372b1a573cd1d51a9f5f))

## [2.0.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v2.0.0...backend-v2.0.1) (2026-05-17)


### Bug Fixes

* initial position detail display ([#753](https://github.com/yuyash/auto-forex-web-service/issues/753)) ([67410ed](https://github.com/yuyash/auto-forex-web-service/commit/67410ed72796a58eccd3fd8b8a965d470291ada6))

## [2.0.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.58.2...backend-v2.0.0) (2026-05-17)


### ⚠ BREAKING CHANGES

* **strategy:** simplify snowball rebuild configuration ([#751](https://github.com/yuyash/auto-forex-web-service/issues/751))

### Features

* **strategy:** simplify snowball rebuild configuration ([#751](https://github.com/yuyash/auto-forex-web-service/issues/751)) ([0c7c08b](https://github.com/yuyash/auto-forex-web-service/commit/0c7c08bf6e92410ed4f9b5eea339c2c11ff11e89))

## [1.58.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.58.1...backend-v1.58.2) (2026-05-17)


### Bug Fixes

* **trading:** mark initial cycles and filter seed positions ([#749](https://github.com/yuyash/auto-forex-web-service/issues/749)) ([c233a40](https://github.com/yuyash/auto-forex-web-service/commit/c233a40289a9ff7e6711460bc00a17bb7f8747a6))

## [1.58.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.58.0...backend-v1.58.1) (2026-05-17)


### Bug Fixes

* **initial-positions:** allow sparse imported layers ([#747](https://github.com/yuyash/auto-forex-web-service/issues/747)) ([e0f0014](https://github.com/yuyash/auto-forex-web-service/commit/e0f00146d2df3e0b0bd711972638e6220ff23375))

## [1.58.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.57.0...backend-v1.58.0) (2026-05-17)


### Features

* **initial-positions:** preserve closed grid slots ([#745](https://github.com/yuyash/auto-forex-web-service/issues/745)) ([7999990](https://github.com/yuyash/auto-forex-web-service/commit/79999903a875a2d79e86de033eff7b3a04af57ec))

## [1.57.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.56.1...backend-v1.57.0) (2026-05-16)


### Features

* **trading:** add cycle anchor controls ([#741](https://github.com/yuyash/auto-forex-web-service/issues/741)) ([7585ea1](https://github.com/yuyash/auto-forex-web-service/commit/7585ea1576a7c1870bf24977fe897b6685d36acd))

## [1.56.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.56.0...backend-v1.56.1) (2026-05-16)


### Bug Fixes

* **trading:** validate sparse initial position slots ([#737](https://github.com/yuyash/auto-forex-web-service/issues/737)) ([48dd303](https://github.com/yuyash/auto-forex-web-service/commit/48dd303aa79b526bbc214f4b94a5023f5d2a470c))

## [1.56.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.55.2...backend-v1.56.0) (2026-05-16)


### Features

* **trading:** import initial positions ([#733](https://github.com/yuyash/auto-forex-web-service/issues/733)) ([95411df](https://github.com/yuyash/auto-forex-web-service/commit/95411dfb118ddad206641f6e7f6e9fbf7836e29e))

## [1.55.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.55.1...backend-v1.55.2) (2026-05-16)


### Bug Fixes

* trading idle resume reconciliation ([#729](https://github.com/yuyash/auto-forex-web-service/issues/729)) ([59a16c3](https://github.com/yuyash/auto-forex-web-service/commit/59a16c30baa447d237f268c51fdf9a84d36e5080))

## [1.55.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.55.0...backend-v1.55.1) (2026-05-16)


### Bug Fixes

* **trading:** keep idle tasks parked on stale ticks ([#726](https://github.com/yuyash/auto-forex-web-service/issues/726)) ([da8ab19](https://github.com/yuyash/auto-forex-web-service/commit/da8ab19aca9302f8d02596483abb17c350e95a9c))

## [1.55.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.54.1...backend-v1.55.0) (2026-05-15)


### Features

* **metrics:** add task throughput and return charts ([#722](https://github.com/yuyash/auto-forex-web-service/issues/722)) ([dd7c166](https://github.com/yuyash/auto-forex-web-service/commit/dd7c1665d71037b4371bd4e5a9ac739c85b036dd))

## [1.54.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.54.0...backend-v1.54.1) (2026-05-15)


### Bug Fixes

* reduce snowball replay overhead ([#721](https://github.com/yuyash/auto-forex-web-service/issues/721)) ([bf57c96](https://github.com/yuyash/auto-forex-web-service/commit/bf57c96769fa393713b8040b2f6641e6d4fef4a3))


### Performance

* **backtest:** reduce snowball replay overhead ([bf57c96](https://github.com/yuyash/auto-forex-web-service/commit/bf57c96769fa393713b8040b2f6641e6d4fef4a3))

## [1.54.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.5...backend-v1.54.0) (2026-05-15)


### Features

* **trading:** add task display currency selection ([#716](https://github.com/yuyash/auto-forex-web-service/issues/716)) ([94465d7](https://github.com/yuyash/auto-forex-web-service/commit/94465d71a2576a876ab94c5052ee67b19fb8aea9))

## [1.53.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.4...backend-v1.53.5) (2026-05-15)


### Bug Fixes

* **trading:** refresh active execution snapshots ([#714](https://github.com/yuyash/auto-forex-web-service/issues/714)) ([9bacdb5](https://github.com/yuyash/auto-forex-web-service/commit/9bacdb5fa814e20e1c045e987014ac59997661b5))

## [1.53.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.3...backend-v1.53.4) (2026-05-14)


### Bug Fixes

* **trading:** retry transient DNS failures during broker drift checks ([#710](https://github.com/yuyash/auto-forex-web-service/issues/710)) ([3c979f8](https://github.com/yuyash/auto-forex-web-service/commit/3c979f80cd7bf7064f77ed45221b64bd6a57645f))

## [1.53.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.2...backend-v1.53.3) (2026-05-14)


### Bug Fixes

* **snowball:** reduce grid violation warning noise ([#708](https://github.com/yuyash/auto-forex-web-service/issues/708)) ([16d2ea8](https://github.com/yuyash/auto-forex-web-service/commit/16d2ea8401d13ed4694424005fb359d2fa87280f))

## [1.53.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.1...backend-v1.53.2) (2026-05-14)


### Refactoring

* backend snowball ([#701](https://github.com/yuyash/auto-forex-web-service/issues/701)) ([dd5ecf0](https://github.com/yuyash/auto-forex-web-service/commit/dd5ecf0df8241bc21925ff9bd71043db2cd7b81a))

## [1.53.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.53.0...backend-v1.53.1) (2026-05-10)


### Bug Fixes

* config revision visibility ([#698](https://github.com/yuyash/auto-forex-web-service/issues/698)) ([05b4f33](https://github.com/yuyash/auto-forex-web-service/commit/05b4f334ca57d00b2a51713e832a4965035e19e5))

## [1.53.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.52.3...backend-v1.53.0) (2026-05-10)


### Features

* **backtest:** seed snowball initial positions ([#695](https://github.com/yuyash/auto-forex-web-service/issues/695)) ([e91b90c](https://github.com/yuyash/auto-forex-web-service/commit/e91b90c0a8ce985730e1ea26b89e37f5464eec74))

## [1.52.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.52.2...backend-v1.52.3) (2026-05-09)


### Bug Fixes

* **trading:** recover idle tasks after deploy ([#693](https://github.com/yuyash/auto-forex-web-service/issues/693)) ([2a3e87d](https://github.com/yuyash/auto-forex-web-service/commit/2a3e87d9e86698077224a0a13a1efc0db70d2fb3))

## [1.52.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.52.1...backend-v1.52.2) (2026-05-08)


### Refactoring

* backend oop services ([#691](https://github.com/yuyash/auto-forex-web-service/issues/691)) ([9009fef](https://github.com/yuyash/auto-forex-web-service/commit/9009fef707c6f6e1dfa2a2824970c58b39471330))

## [1.52.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.52.0...backend-v1.52.1) (2026-05-08)


### Bug Fixes

* snowball cross layer counter ordering ([#689](https://github.com/yuyash/auto-forex-web-service/issues/689)) ([04553dc](https://github.com/yuyash/auto-forex-web-service/commit/04553dcfb1fccb089459fb193e502a34ed08d8a4))

## [1.52.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.6...backend-v1.52.0) (2026-05-07)


### Features

* **trading:** paginate and filter strategy cycle list server-side ([#687](https://github.com/yuyash/auto-forex-web-service/issues/687)) ([6b466d2](https://github.com/yuyash/auto-forex-web-service/commit/6b466d2e502c77902247c965e00e0fa53de358fc))

## [1.51.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.5...backend-v1.51.6) (2026-05-07)


### Bug Fixes

* **trading:** keep positions on deploy stop ([#685](https://github.com/yuyash/auto-forex-web-service/issues/685)) ([b7e88e2](https://github.com/yuyash/auto-forex-web-service/commit/b7e88e23e25aed8b83390be4ccea27c6df31e7b6))

## [1.51.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.4...backend-v1.51.5) (2026-05-07)


### Bug Fixes

* **snowball:** tolerate grid close order drift ([#683](https://github.com/yuyash/auto-forex-web-service/issues/683)) ([a99a61e](https://github.com/yuyash/auto-forex-web-service/commit/a99a61ea79a3a78020c2db6842c7c5bbfbc11e2b))

## [1.51.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.3...backend-v1.51.4) (2026-05-07)


### Bug Fixes

* account units guards ([#681](https://github.com/yuyash/auto-forex-web-service/issues/681)) ([a371402](https://github.com/yuyash/auto-forex-web-service/commit/a3714027db19ddc4868655c15fa24e262860f471))

## [1.51.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.2...backend-v1.51.3) (2026-05-06)


### Bug Fixes

* **account:** configure live unit guards ([10eefbc](https://github.com/yuyash/auto-forex-web-service/commit/10eefbc3669432f6636bc82d937ea854faa4a73e))
* configure account unit guards ([#679](https://github.com/yuyash/auto-forex-web-service/issues/679)) ([10eefbc](https://github.com/yuyash/auto-forex-web-service/commit/10eefbc3669432f6636bc82d937ea854faa4a73e))

## [1.51.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.1...backend-v1.51.2) (2026-05-06)


### Bug Fixes

* **trading:** correct live order timestamps and account limits ([#677](https://github.com/yuyash/auto-forex-web-service/issues/677)) ([763fbf7](https://github.com/yuyash/auto-forex-web-service/commit/763fbf7087aad72fa6a0949a8220ddd2c20b7f13))

## [1.51.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.51.0...backend-v1.51.1) (2026-05-06)


### Bug Fixes

* **backtest:** refresh balance adjustment state ([#675](https://github.com/yuyash/auto-forex-web-service/issues/675)) ([f59ecb4](https://github.com/yuyash/auto-forex-web-service/commit/f59ecb4a6a27323d5325a9e5428433037bcb2455))

## [1.51.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.50.1...backend-v1.51.0) (2026-05-06)


### Features

* backtest balance adjustment ([#673](https://github.com/yuyash/auto-forex-web-service/issues/673)) ([d7a9897](https://github.com/yuyash/auto-forex-web-service/commit/d7a9897ac7bd6e8bc5d80027f934bd896319134d))

## [1.50.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.50.0...backend-v1.50.1) (2026-05-05)


### Bug Fixes

* **trading:** record Trade on sell_on_stop and add loss-cut chart markers ([#671](https://github.com/yuyash/auto-forex-web-service/issues/671)) ([89c27e4](https://github.com/yuyash/auto-forex-web-service/commit/89c27e404db9f4394deba38e7715860a2b8f9756))

## [1.50.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.49.4...backend-v1.50.0) (2026-05-05)


### Features

* **strategy:** add independent SnowballNet controls ([#670](https://github.com/yuyash/auto-forex-web-service/issues/670)) ([7485e57](https://github.com/yuyash/auto-forex-web-service/commit/7485e57ba9dc770eb6131056f7f98571cd9f712b))


### Bug Fixes

* **market:** log load data command output ([#668](https://github.com/yuyash/auto-forex-web-service/issues/668)) ([9617605](https://github.com/yuyash/auto-forex-web-service/commit/9617605cc79f3938b84188e1fc417e110ce5dd5b))

## [1.49.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.49.3...backend-v1.49.4) (2026-05-05)


### Bug Fixes

* snowball net metrics range ([#664](https://github.com/yuyash/auto-forex-web-service/issues/664)) ([8e257c6](https://github.com/yuyash/auto-forex-web-service/commit/8e257c6314ef01ec91fc1a9e8693814687e10f23))

## [1.49.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.49.2...backend-v1.49.3) (2026-05-05)


### Bug Fixes

* snowball net config exclusivity ([#662](https://github.com/yuyash/auto-forex-web-service/issues/662)) ([06e5ef8](https://github.com/yuyash/auto-forex-web-service/commit/06e5ef8d25eb36b2f22d17b7ea5e3d629d6d167f))

## [1.49.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.49.1...backend-v1.49.2) (2026-05-05)


### Performance

* **strategy:** improve SnowballNet chart loading ([#659](https://github.com/yuyash/auto-forex-web-service/issues/659)) ([57a0b26](https://github.com/yuyash/auto-forex-web-service/commit/57a0b26ecb95ae8dee46c131c98c3d75ddf02494))

## [1.49.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.49.0...backend-v1.49.1) (2026-05-04)


### Bug Fixes

* snowball net follow chart lines ([#655](https://github.com/yuyash/auto-forex-web-service/issues/655)) ([2f061d3](https://github.com/yuyash/auto-forex-web-service/commit/2f061d375c408acc37c68d52fd4877a89eaa2b48))

## [1.49.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.48.2...backend-v1.49.0) (2026-05-04)


### Features

* **snowball-net:** add adaptive risk controls ([#653](https://github.com/yuyash/auto-forex-web-service/issues/653)) ([eb84d50](https://github.com/yuyash/auto-forex-web-service/commit/eb84d502e4c1b3eb3f3aea2a14f02e63b83635a9))


### Bug Fixes

* snowball chart follow window ([#651](https://github.com/yuyash/auto-forex-web-service/issues/651)) ([16c3e31](https://github.com/yuyash/auto-forex-web-service/commit/16c3e3161c93d18355066893fc8c2bd272acc997))

## [1.48.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.48.1...backend-v1.48.2) (2026-05-03)


### Bug Fixes

* **market:** persist daily tick load events ([#649](https://github.com/yuyash/auto-forex-web-service/issues/649)) ([739d250](https://github.com/yuyash/auto-forex-web-service/commit/739d25009a30d0ebc0c2277278f5f98f07731c86))

## [1.48.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.48.0...backend-v1.48.1) (2026-05-03)


### Bug Fixes

* safari chart sizing ([#642](https://github.com/yuyash/auto-forex-web-service/issues/642)) ([e472bb8](https://github.com/yuyash/auto-forex-web-service/commit/e472bb84a46bcbe15aae15602805213a7b26a573))

## [1.48.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.47.0...backend-v1.48.0) (2026-05-03)


### Features

* snowball net chart order UI ([#637](https://github.com/yuyash/auto-forex-web-service/issues/637)) ([6509b87](https://github.com/yuyash/auto-forex-web-service/commit/6509b873f0a4d9a7839689e0b6429f939796a98c))

## [1.47.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.46.2...backend-v1.47.0) (2026-05-03)


### Features

* snowball net strategy ([#634](https://github.com/yuyash/auto-forex-web-service/issues/634)) ([a8ad8a0](https://github.com/yuyash/auto-forex-web-service/commit/a8ad8a07029c8716ace199b6d202f2f5dfffd388))


### Bug Fixes

* **snowball:** clamp layer initial take profit ([#636](https://github.com/yuyash/auto-forex-web-service/issues/636)) ([34b7c26](https://github.com/yuyash/auto-forex-web-service/commit/34b7c26501e6ab9f75a83b6a686207c209249aa3))

## [1.46.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.46.1...backend-v1.46.2) (2026-05-02)


### Performance

* metrics api pagination and mobile layout ([#632](https://github.com/yuyash/auto-forex-web-service/issues/632)) ([810c267](https://github.com/yuyash/auto-forex-web-service/commit/810c267593b9be01d338d9d4b25a2e80681ff263))

## [1.46.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.46.0...backend-v1.46.1) (2026-05-02)


### Bug Fixes

* **trading:** accept OANDA-style granularity tokens in metrics API ([#630](https://github.com/yuyash/auto-forex-web-service/issues/630)) ([fbc0d2d](https://github.com/yuyash/auto-forex-web-service/commit/fbc0d2d377277975bb8a290e9b5a5e8bcc208bc8))

## [1.46.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.45.2...backend-v1.46.0) (2026-05-02)


### Features

* rebuild take profit mode ([#624](https://github.com/yuyash/auto-forex-web-service/issues/624)) ([9d68b8a](https://github.com/yuyash/auto-forex-web-service/commit/9d68b8a8490ca9c818d803654e121b92b31c86fd))
* refactoring and improve separation of concerns. ([#627](https://github.com/yuyash/auto-forex-web-service/issues/627)) ([670a0c8](https://github.com/yuyash/auto-forex-web-service/commit/670a0c872bb8a5a03d69b6d6587b9b0801280851))
* **snowball:** recover stop-loss pips on rebuild ([#626](https://github.com/yuyash/auto-forex-web-service/issues/626)) ([406b8ea](https://github.com/yuyash/auto-forex-web-service/commit/406b8ead4d31703c3c82881c2ecf5454b8ea8956))
* task detail controls and snowball docs ([#629](https://github.com/yuyash/auto-forex-web-service/issues/629)) ([60cc632](https://github.com/yuyash/auto-forex-web-service/commit/60cc63209aae517518f95dba0be26b1fbb8de67e))


### Bug Fixes

* harden auth session ([#628](https://github.com/yuyash/auto-forex-web-service/issues/628)) ([b6e798b](https://github.com/yuyash/auto-forex-web-service/commit/b6e798b53cf567a10e406fd351f4591ee42205c5))
* **snowball:** allow disabled preserve threshold omission ([#625](https://github.com/yuyash/auto-forex-web-service/issues/625)) ([13501df](https://github.com/yuyash/auto-forex-web-service/commit/13501dfcf8524ac698017968b7e03597365bb59d))


### Refactoring

* **adaptive-net:** add cost-aware decision gates ([#623](https://github.com/yuyash/auto-forex-web-service/issues/623)) ([ec3a623](https://github.com/yuyash/auto-forex-web-service/commit/ec3a623537bceef65110e89912d6242694d3eec3))
* **frontend:** harden task detail mobile layouts ([#622](https://github.com/yuyash/auto-forex-web-service/issues/622)) ([d92706f](https://github.com/yuyash/auto-forex-web-service/commit/d92706f213f2aed839894a9f297eab69386c80b1))

## [1.45.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.45.1...backend-v1.45.2) (2026-04-26)


### Refactoring

* task polling throttle fix ([#618](https://github.com/yuyash/auto-forex-web-service/issues/618)) ([98c823d](https://github.com/yuyash/auto-forex-web-service/commit/98c823d31c6137c753858afcd372606d0148b75e))

## [1.45.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.45.0...backend-v1.45.1) (2026-04-26)


### Bug Fixes

* **trading:** stabilize backtest execution ([#616](https://github.com/yuyash/auto-forex-web-service/issues/616)) ([8ace3af](https://github.com/yuyash/auto-forex-web-service/commit/8ace3afe182b33b05bdb1bed65f0e383153cd81b))

## [1.45.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.44.0...backend-v1.45.0) (2026-04-26)


### Features

* **adaptive-net:** chart normalized strategy signals ([#614](https://github.com/yuyash/auto-forex-web-service/issues/614)) ([7b5a355](https://github.com/yuyash/auto-forex-web-service/commit/7b5a35504710faf497855478815f952e22d8b60b))

## [1.44.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.43.2...backend-v1.44.0) (2026-04-26)


### Features

* security observability updates ([#612](https://github.com/yuyash/auto-forex-web-service/issues/612)) ([c545e5c](https://github.com/yuyash/auto-forex-web-service/commit/c545e5c401c29b411c87489817b52da0352d9235))

## [1.43.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.43.1...backend-v1.43.2) (2026-04-26)


### Bug Fixes

* snowball rebuild tp and cycle accounting ([#610](https://github.com/yuyash/auto-forex-web-service/issues/610)) ([9d73872](https://github.com/yuyash/auto-forex-web-service/commit/9d73872642251d27ce5cab1968f0a8fd28dda278))

## [1.43.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.43.0...backend-v1.43.1) (2026-04-25)


### Refactoring

* responsibility boundaries ([#608](https://github.com/yuyash/auto-forex-web-service/issues/608)) ([bf7d3bc](https://github.com/yuyash/auto-forex-web-service/commit/bf7d3bc9836546017884c41cc588dee45a2b2b25))

## [1.43.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.7...backend-v1.43.0) (2026-04-25)


### Features

* security observability updates ([#606](https://github.com/yuyash/auto-forex-web-service/issues/606)) ([55dfa3c](https://github.com/yuyash/auto-forex-web-service/commit/55dfa3cd6975581af25fc5a8fc329adf3348c7a5))

## [1.42.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.6...backend-v1.42.7) (2026-04-24)


### Bug Fixes

* improve task detail and dashboard UI ([#593](https://github.com/yuyash/auto-forex-web-service/issues/593)) ([12a88ba](https://github.com/yuyash/auto-forex-web-service/commit/12a88ba5d1ffa2f65349e323c7d45e9d4778ed33))

## [1.42.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.5...backend-v1.42.6) (2026-04-24)


### Refactoring

* codebase quality pass ([#590](https://github.com/yuyash/auto-forex-web-service/issues/590)) ([6046edd](https://github.com/yuyash/auto-forex-web-service/commit/6046edd32a3763f56feed0fb81f140c3406f18ba))

## [1.42.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.4...backend-v1.42.5) (2026-04-23)


### Bug Fixes

* backtest sell on stop field mapping ([#588](https://github.com/yuyash/auto-forex-web-service/issues/588)) ([fa0ed47](https://github.com/yuyash/auto-forex-web-service/commit/fa0ed478b9122f616096e0b0cc677df411caf2d5))

## [1.42.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.3...backend-v1.42.4) (2026-04-23)


### Bug Fixes

* **strategy:** guard layer initial entry against grid ordering violation ([#586](https://github.com/yuyash/auto-forex-web-service/issues/586)) ([f27ef62](https://github.com/yuyash/auto-forex-web-service/commit/f27ef624d7ffecafd2752d22a9fef9aba8114937))

## [1.42.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.2...backend-v1.42.3) (2026-04-22)


### Bug Fixes

* **strategy:** clamp rebuild entry price to preserve grid ordering ([#584](https://github.com/yuyash/auto-forex-web-service/issues/584)) ([4a5f999](https://github.com/yuyash/auto-forex-web-service/commit/4a5f9996282033d653119ae96b46853c10d6b9da))

## [1.42.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.1...backend-v1.42.2) (2026-04-22)


### Bug Fixes

* **strategy:** show historical slot loss-cut states ([#582](https://github.com/yuyash/auto-forex-web-service/issues/582)) ([c3ab2b4](https://github.com/yuyash/auto-forex-web-service/commit/c3ab2b49143bc7f1fbdacc8862a95917effa87a2))

## [1.42.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.42.0...backend-v1.42.1) (2026-04-22)


### Bug Fixes

* **backtest:** prevent silent tick loss and add batch-level observabi… ([#580](https://github.com/yuyash/auto-forex-web-service/issues/580)) ([84de5a3](https://github.com/yuyash/auto-forex-web-service/commit/84de5a37018faa81c7c4afbf4bbacd94f2ae41ed))
* **backtest:** prevent silent tick loss and add batch-level observability ([84de5a3](https://github.com/yuyash/auto-forex-web-service/commit/84de5a37018faa81c7c4afbf4bbacd94f2ae41ed))

## [1.42.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.8...backend-v1.42.0) (2026-04-21)


### Features

* **strategy:** configure rebuild stop loss ([#576](https://github.com/yuyash/auto-forex-web-service/issues/576)) ([205b98b](https://github.com/yuyash/auto-forex-web-service/commit/205b98b54fc5f084658af2393d007d08f0e1c8b4))

## [1.41.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.7...backend-v1.41.8) (2026-04-21)


### Bug Fixes

* **strategy:** show close trade pnl in jpy ([#574](https://github.com/yuyash/auto-forex-web-service/issues/574)) ([af7f414](https://github.com/yuyash/auto-forex-web-service/commit/af7f41430ab3b03233d35a1e5fec53640f5204ef))

## [1.41.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.6...backend-v1.41.7) (2026-04-21)


### Bug Fixes

* **backtest:** make tick gap threshold configurable ([#572](https://github.com/yuyash/auto-forex-web-service/issues/572)) ([e055e9f](https://github.com/yuyash/auto-forex-web-service/commit/e055e9f3eea2e4894e1e02244144bdbce8b12709))

## [1.41.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.5...backend-v1.41.6) (2026-04-21)


### Bug Fixes

* **strategy:** restore snowball stop loss auto mode ([#570](https://github.com/yuyash/auto-forex-web-service/issues/570)) ([eca4503](https://github.com/yuyash/auto-forex-web-service/commit/eca45035d9725b955248342c5a37ec3a3c1fb2c6))

## [1.41.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.4...backend-v1.41.5) (2026-04-21)


### Bug Fixes

* **strategy:** guard snowball grid ordering validation ([#567](https://github.com/yuyash/auto-forex-web-service/issues/567)) ([771005b](https://github.com/yuyash/auto-forex-web-service/commit/771005b38606e9083757faa6bb9985f6578b95ed))

## [1.41.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.3...backend-v1.41.4) (2026-04-21)


### Bug Fixes

* **snowball:** re-trigger release-please for cross-layer TP bound fix ([#565](https://github.com/yuyash/auto-forex-web-service/issues/565)) ([575be2d](https://github.com/yuyash/auto-forex-web-service/commit/575be2d0352ed00621ff1894f1954ae65abf4a8a))

## [1.41.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.2...backend-v1.41.3) (2026-04-20)


### Bug Fixes

* **snowball:** sync actual fill prices into strategy state ([#562](https://github.com/yuyash/auto-forex-web-service/issues/562)) ([e7c5130](https://github.com/yuyash/auto-forex-web-service/commit/e7c51304652cebd9474d1e435c491067ec820e7c))

## [1.41.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.1...backend-v1.41.2) (2026-04-20)


### Bug Fixes

* **snowball:** prevent lower-slot refills below active counters ([#559](https://github.com/yuyash/auto-forex-web-service/issues/559)) ([51b467f](https://github.com/yuyash/auto-forex-web-service/commit/51b467feae3ebbff1017f9a7d7d8ef73f5106069))

## [1.41.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.41.0...backend-v1.41.1) (2026-04-20)


### Bug Fixes

* **snowball:** clamp rebuild TP to upper grid neighbour ([#557](https://github.com/yuyash/auto-forex-web-service/issues/557)) ([827793e](https://github.com/yuyash/auto-forex-web-service/commit/827793e82cff31394173c9aa54fa1e12f972ca1b))

## [1.41.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.40.0...backend-v1.41.0) (2026-04-20)


### Features

* backtest market idle ([#554](https://github.com/yuyash/auto-forex-web-service/issues/554)) ([0747848](https://github.com/yuyash/auto-forex-web-service/commit/074784846b3ba40beba601a4e299ed838e880fde))

## [1.40.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.39.1...backend-v1.40.0) (2026-04-19)


### Features

* filter by id in task detail tables ([#553](https://github.com/yuyash/auto-forex-web-service/issues/553)) ([e6bb0bf](https://github.com/yuyash/auto-forex-web-service/commit/e6bb0bfc03168303136ec6b8cd6031df9bbd9a94))

## [1.39.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.39.0...backend-v1.39.1) (2026-04-19)


### Bug Fixes

* **trading:** separate celery_task_id from execution_id ([#550](https://github.com/yuyash/auto-forex-web-service/issues/550)) ([5251042](https://github.com/yuyash/auto-forex-web-service/commit/5251042b1e07ceac83d3eaf764af12926470b77d))

## [1.39.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.38.1...backend-v1.39.0) (2026-04-19)


### Features

* **ui,backend:** add stop reason, tidy log precision, fix resume ([#547](https://github.com/yuyash/auto-forex-web-service/issues/547)) ([2857315](https://github.com/yuyash/auto-forex-web-service/commit/285731593956213edf107f4e7554e18236f71b30))

## [1.38.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.38.0...backend-v1.38.1) (2026-04-19)


### Bug Fixes

* **backtest:** isolate stream per execution and purge stale state ([#544](https://github.com/yuyash/auto-forex-web-service/issues/544)) ([df126f6](https://github.com/yuyash/auto-forex-web-service/commit/df126f67f5307aa342ab8be5484b1dbb3b8b30da))

## [1.38.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.37.1...backend-v1.38.0) (2026-04-19)


### Features

* **snowball:** cycle/lifecycle P/L warnings and same-tick counter adds ([#543](https://github.com/yuyash/auto-forex-web-service/issues/543)) ([65293c6](https://github.com/yuyash/auto-forex-web-service/commit/65293c639793f18f6c2c8ca592ab81cada4c41cf))

## [1.37.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.37.0...backend-v1.37.1) (2026-04-19)


### Bug Fixes

* task lifecycle followups ([#541](https://github.com/yuyash/auto-forex-web-service/issues/541)) ([c4c3737](https://github.com/yuyash/auto-forex-web-service/commit/c4c373791fb9427d54d5bd3c7f9071a0954b4234))

## [1.37.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.36.3...backend-v1.37.0) (2026-04-18)


### Features

* task lifecycle enhancements ([#538](https://github.com/yuyash/auto-forex-web-service/issues/538)) ([5622195](https://github.com/yuyash/auto-forex-web-service/commit/5622195a832019477c670b9c72b3eb1f324693ab))

## [1.36.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.36.2...backend-v1.36.3) (2026-04-18)


### Bug Fixes

* **backtest:** deliver ticks over Redis Streams with backpressure and gap detection ([9eccfac](https://github.com/yuyash/auto-forex-web-service/commit/9eccfac00554294fbcdc5157cd5e2dbe82acb61d))
* **backtest:** deliver ticks over Redis Streams with backpressure and… ([#536](https://github.com/yuyash/auto-forex-web-service/issues/536)) ([9eccfac](https://github.com/yuyash/auto-forex-web-service/commit/9eccfac00554294fbcdc5157cd5e2dbe82acb61d))

## [1.36.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.36.1...backend-v1.36.2) (2026-04-17)


### Bug Fixes

* multi issue UI backend improvements ([#531](https://github.com/yuyash/auto-forex-web-service/issues/531)) ([2a6b9b1](https://github.com/yuyash/auto-forex-web-service/commit/2a6b9b1df5615197815280f3c6322a681deb2ede))

## [1.36.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.36.0...backend-v1.36.1) (2026-04-16)


### Bug Fixes

* historical execution display ([#519](https://github.com/yuyash/auto-forex-web-service/issues/519)) ([6862822](https://github.com/yuyash/auto-forex-web-service/commit/6862822160da0da8b20029824301b8c74bfd1ffa))

## [1.36.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.35.0...backend-v1.36.0) (2026-04-16)


### Features

* execution config snapshot ([#515](https://github.com/yuyash/auto-forex-web-service/issues/515)) ([768c15f](https://github.com/yuyash/auto-forex-web-service/commit/768c15fc21bbfb65917ab5de2032d82c8040b5ea))

## [1.35.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.12...backend-v1.35.0) (2026-04-16)


### Features

* scheduled athena tick load ([#511](https://github.com/yuyash/auto-forex-web-service/issues/511)) ([37110a9](https://github.com/yuyash/auto-forex-web-service/commit/37110a9ecf35b9ea85ef3baa6ac6688f4b8710ea))

## [1.34.12](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.11...backend-v1.34.12) (2026-04-16)


### Bug Fixes

* lifecycle pnl and timestamps ([#509](https://github.com/yuyash/auto-forex-web-service/issues/509)) ([1d0fa40](https://github.com/yuyash/auto-forex-web-service/commit/1d0fa4083e46e327abc1c5ddc2e74ac23c5dd176))

## [1.34.11](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.10...backend-v1.34.11) (2026-04-15)


### Bug Fixes

* **frontend:** refresh task cache after updates ([#507](https://github.com/yuyash/auto-forex-web-service/issues/507)) ([d9005b3](https://github.com/yuyash/auto-forex-web-service/commit/d9005b337bde247600ca9774d523ef46a45cf4c5))

## [1.34.10](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.9...backend-v1.34.10) (2026-04-15)


### Bug Fixes

* trading metrics summary align ([#505](https://github.com/yuyash/auto-forex-web-service/issues/505)) ([1b6c369](https://github.com/yuyash/auto-forex-web-service/commit/1b6c36949eec0df9df11300a43331dad35409629))

## [1.34.9](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.8...backend-v1.34.9) (2026-04-14)


### Bug Fixes

* replay event markers ([#495](https://github.com/yuyash/auto-forex-web-service/issues/495)) ([e4636b3](https://github.com/yuyash/auto-forex-web-service/commit/e4636b371675385b809cf44fc5d110c655257617))

## [1.34.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.7...backend-v1.34.8) (2026-04-14)


### Bug Fixes

* deploy resume and oanda link ([#492](https://github.com/yuyash/auto-forex-web-service/issues/492)) ([c85aaa4](https://github.com/yuyash/auto-forex-web-service/commit/c85aaa4b0262621e1a6de5ce409dba2eec920444))

## [1.34.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.6...backend-v1.34.7) (2026-04-14)


### Bug Fixes

* trigger production release ([#490](https://github.com/yuyash/auto-forex-web-service/issues/490)) ([0d9d0cf](https://github.com/yuyash/auto-forex-web-service/commit/0d9d0cf7448acaab761171f39476ee91bc21ff4b))

## [1.34.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.5...backend-v1.34.6) (2026-04-14)


### Bug Fixes

* **trading:** harden task recovery after deploy restarts ([#487](https://github.com/yuyash/auto-forex-web-service/issues/487)) ([3afd1bc](https://github.com/yuyash/auto-forex-web-service/commit/3afd1bc0f03aa807dd47ff8433fe9bfa36403061))

## [1.34.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.4...backend-v1.34.5) (2026-04-14)


### Bug Fixes

* trading restart recovery UI ([#484](https://github.com/yuyash/auto-forex-web-service/issues/484)) ([1e6573c](https://github.com/yuyash/auto-forex-web-service/commit/1e6573cdc42e7bca630b25ed5c08940454d725e5))

## [1.34.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.3...backend-v1.34.4) (2026-04-13)


### Bug Fixes

* **backtest:** avoid false orphan restart failures ([#482](https://github.com/yuyash/auto-forex-web-service/issues/482)) ([c227b62](https://github.com/yuyash/auto-forex-web-service/commit/c227b62991a1cb4aafb84c1f8621335b8bb8e0d9))

## [1.34.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.2...backend-v1.34.3) (2026-04-13)


### Bug Fixes

* stop live broker drift and repair deploy drain ([#479](https://github.com/yuyash/auto-forex-web-service/issues/479)) ([85395bb](https://github.com/yuyash/auto-forex-web-service/commit/85395bb377bc4a1e628fd53932b39cde4c7f233b))

## [1.34.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.1...backend-v1.34.2) (2026-04-13)


### Bug Fixes

* **trading:** resume snowball tasks after deploy ([#474](https://github.com/yuyash/auto-forex-web-service/issues/474)) ([bb679f6](https://github.com/yuyash/auto-forex-web-service/commit/bb679f68ddec3f2348659d97734d07ac60fc33b3))

## [1.34.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.34.0...backend-v1.34.1) (2026-04-13)


### Bug Fixes

* **frontend:** add task summary locale keys ([#472](https://github.com/yuyash/auto-forex-web-service/issues/472)) ([2aa4d31](https://github.com/yuyash/auto-forex-web-service/commit/2aa4d310fc8b91fad2dc585e2dbe1f7cd789de05))

## [1.34.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.10...backend-v1.34.0) (2026-04-13)


### Features

* **market:** add account detail history filters ([#470](https://github.com/yuyash/auto-forex-web-service/issues/470)) ([2110d30](https://github.com/yuyash/auto-forex-web-service/commit/2110d3035adc7d98fa7db34140d4c3fec4ffbc33))

## [1.33.10](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.9...backend-v1.33.10) (2026-04-13)


### Bug Fixes

* **frontend:** stack position actions on account detail ([#467](https://github.com/yuyash/auto-forex-web-service/issues/467)) ([787c695](https://github.com/yuyash/auto-forex-web-service/commit/787c695a192c45ed751122a8d3ad14944d1ac21b))

## [1.33.9](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.8...backend-v1.33.9) (2026-04-13)


### Bug Fixes

* task capacity and snowball ordering ([#465](https://github.com/yuyash/auto-forex-web-service/issues/465)) ([48e3fa0](https://github.com/yuyash/auto-forex-web-service/commit/48e3fa0087b90ea9efebf521fa73702a24d36251))

## [1.33.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.7...backend-v1.33.8) (2026-04-13)


### Bug Fixes

* **market:** harden trading task tick orchestration ([#463](https://github.com/yuyash/auto-forex-web-service/issues/463)) ([8d5384a](https://github.com/yuyash/auto-forex-web-service/commit/8d5384ac3361ed4fe1e57921c042c91b598d437d))

## [1.33.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.6...backend-v1.33.7) (2026-04-13)


### Bug Fixes

* **trading:** ignore stale market heartbeats in capacity ([#461](https://github.com/yuyash/auto-forex-web-service/issues/461)) ([f065d18](https://github.com/yuyash/auto-forex-web-service/commit/f065d181111fa32580715886fbb8d81ae82f699c))

## [1.33.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.5...backend-v1.33.6) (2026-04-13)


### Bug Fixes

* **celery:** isolate control workers and gate task starts ([#459](https://github.com/yuyash/auto-forex-web-service/issues/459)) ([791ded4](https://github.com/yuyash/auto-forex-web-service/commit/791ded457da8ba058f579a01559304ae7deece84))

## [1.33.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.4...backend-v1.33.5) (2026-04-13)


### Bug Fixes

* lifecycle summary strategy guards ([#457](https://github.com/yuyash/auto-forex-web-service/issues/457)) ([69ae249](https://github.com/yuyash/auto-forex-web-service/commit/69ae2497a7f47565be156fcb3796db3a8bea8be5))

## [1.33.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.3...backend-v1.33.4) (2026-04-12)


### Bug Fixes

* **api:** ignore task ordering on subresources ([#455](https://github.com/yuyash/auto-forex-web-service/issues/455)) ([7496dea](https://github.com/yuyash/auto-forex-web-service/commit/7496dea00144d3bffa6bf47ba7df6336c0fc2d4b))

## [1.33.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.2...backend-v1.33.3) (2026-04-12)


### Bug Fixes

* strategy overview trade pagination ([#453](https://github.com/yuyash/auto-forex-web-service/issues/453)) ([ec02946](https://github.com/yuyash/auto-forex-web-service/commit/ec029467139ba15b19513797f75f380c07967583))

## [1.33.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.1...backend-v1.33.2) (2026-04-12)


### Bug Fixes

* snowball weighted avg double count r0 ([#451](https://github.com/yuyash/auto-forex-web-service/issues/451)) ([254cb91](https://github.com/yuyash/auto-forex-web-service/commit/254cb91947e6d706caa8007e86d6381285aa2f54))

## [1.33.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.33.0...backend-v1.33.1) (2026-04-12)


### Bug Fixes

* backtest tick granularity edit ([#449](https://github.com/yuyash/auto-forex-web-service/issues/449)) ([d888807](https://github.com/yuyash/auto-forex-web-service/commit/d88880722bb5cb8364c548413e76f9f6191c0af9))

## [1.33.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.32.1...backend-v1.33.0) (2026-04-12)


### Features

* **strategy:** preserve highest snowball R on stop-loss ([#447](https://github.com/yuyash/auto-forex-web-service/issues/447)) ([8f1ed6e](https://github.com/yuyash/auto-forex-web-service/commit/8f1ed6ef1b7a8df7bf25db9c713cb7d3a985a88f))

## [1.32.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.32.0...backend-v1.32.1) (2026-04-12)


### Bug Fixes

* **strategy:** remove empty layer after higher-layer r0 tp ([#442](https://github.com/yuyash/auto-forex-web-service/issues/442)) ([f69139a](https://github.com/yuyash/auto-forex-web-service/commit/f69139a1859f4a825597c30247e8613e85b8c91a))

## [1.32.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.31.0...backend-v1.32.0) (2026-04-11)


### Features

* **strategy:** add snowball grid state indicator ([#426](https://github.com/yuyash/auto-forex-web-service/issues/426)) ([f38445f](https://github.com/yuyash/auto-forex-web-service/commit/f38445fd48b1f8a453673edbe68ed9e1bd71a8bb))

## [1.31.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.30.3...backend-v1.31.0) (2026-04-11)


### Features

* **backtest:** add replay granularity aggregation modes ([#424](https://github.com/yuyash/auto-forex-web-service/issues/424)) ([ebd1e7a](https://github.com/yuyash/auto-forex-web-service/commit/ebd1e7ad6d62900d6911b5facaeda017b6a2fdb3))

## [1.30.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.30.2...backend-v1.30.3) (2026-04-11)


### Bug Fixes

* **snowball:** align f_max with max layer count ([#422](https://github.com/yuyash/auto-forex-web-service/issues/422)) ([3b0afad](https://github.com/yuyash/auto-forex-web-service/commit/3b0afada8d75679b580bbe5b2af52f218d718445))

## [1.30.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.30.1...backend-v1.30.2) (2026-04-11)


### Bug Fixes

* **trading:** add snowball rebuild loss-cut toggle ([#418](https://github.com/yuyash/auto-forex-web-service/issues/418)) ([64eb07f](https://github.com/yuyash/auto-forex-web-service/commit/64eb07f469cb6cb2b557b7946f930983b17fec1a))

## [1.30.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.30.0...backend-v1.30.1) (2026-04-11)


### Bug Fixes

* **strategy:** unseal higher slots when a refillable counter is re-op… ([#414](https://github.com/yuyash/auto-forex-web-service/issues/414)) ([8249075](https://github.com/yuyash/auto-forex-web-service/commit/82490755d5575db1be2a2ee983b2edd15d2f61b5))
* **strategy:** unseal higher slots when a refillable counter is re-opened ([8249075](https://github.com/yuyash/auto-forex-web-service/commit/82490755d5575db1be2a2ee983b2edd15d2f61b5))

## [1.30.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.29.0...backend-v1.30.0) (2026-04-11)


### Features

* add pnl to cycle ([#412](https://github.com/yuyash/auto-forex-web-service/issues/412)) ([c036e8e](https://github.com/yuyash/auto-forex-web-service/commit/c036e8e5c4ef34c3743455927a42b60e486eed9e))

## [1.29.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.18...backend-v1.29.0) (2026-04-10)


### Features

* reseed on all slots pending ([#410](https://github.com/yuyash/auto-forex-web-service/issues/410)) ([1410383](https://github.com/yuyash/auto-forex-web-service/commit/141038387485ecd24f1df13e543950f7b874894f))

## [1.28.18](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.17...backend-v1.28.18) (2026-04-10)


### Bug Fixes

* **strategy:** include pending-rebuild slots in weighted-avg TP calcu… ([#408](https://github.com/yuyash/auto-forex-web-service/issues/408)) ([4243626](https://github.com/yuyash/auto-forex-web-service/commit/42436262e8435bb60d7825ab691cbfa22661fe8c))
* **strategy:** include pending-rebuild slots in weighted-avg TP calculation ([4243626](https://github.com/yuyash/auto-forex-web-service/commit/42436262e8435bb60d7825ab691cbfa22661fe8c))

## [1.28.17](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.16...backend-v1.28.17) (2026-04-10)


### Bug Fixes

* **trading:** resolve rebuild cycle_id misattribution and error exposure ([#405](https://github.com/yuyash/auto-forex-web-service/issues/405)) ([f54a5a6](https://github.com/yuyash/auto-forex-web-service/commit/f54a5a629a4dbe6aee29655a3a9576aca60e57d9))

## [1.28.16](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.15...backend-v1.28.16) (2026-04-10)


### Bug Fixes

* **trading:** refactor cycle lifecycle and stop-loss integration ([#403](https://github.com/yuyash/auto-forex-web-service/issues/403)) ([2fafde3](https://github.com/yuyash/auto-forex-web-service/commit/2fafde317ea605ad5f87974a5743323eba745a0c))

## [1.28.15](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.14...backend-v1.28.15) (2026-04-09)


### Bug Fixes

* **trading:** fix weighted-avg TP, lifecycle display, and refactor re… ([#399](https://github.com/yuyash/auto-forex-web-service/issues/399)) ([b4b78dc](https://github.com/yuyash/auto-forex-web-service/commit/b4b78dc7aa6c04709006f2eb5bca51352575079e))
* **trading:** fix weighted-avg TP, lifecycle display, and refactor rebuild handler ([b4b78dc](https://github.com/yuyash/auto-forex-web-service/commit/b4b78dc7aa6c04709006f2eb5bca51352575079e))

## [1.28.14](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.13...backend-v1.28.14) (2026-04-09)


### Bug Fixes

* backtest pnl and snowball counter adds ([#397](https://github.com/yuyash/auto-forex-web-service/issues/397)) ([ab9c458](https://github.com/yuyash/auto-forex-web-service/commit/ab9c45801482765721fa6df0598b3fc4c7f873b0))

## [1.28.13](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.12...backend-v1.28.13) (2026-04-09)


### Bug Fixes

* **metrics:** align metrics tab PnL with overview tab using quote-currency accumulation ([#395](https://github.com/yuyash/auto-forex-web-service/issues/395)) ([2c3fb31](https://github.com/yuyash/auto-forex-web-service/commit/2c3fb3112d6cf066d38e31b020b0d44677a5632a))

## [1.28.12](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.11...backend-v1.28.12) (2026-04-09)


### Bug Fixes

* **metrics:** compute total_return directly from converted total_pnl ([#393](https://github.com/yuyash/auto-forex-web-service/issues/393)) ([351c4bd](https://github.com/yuyash/auto-forex-web-service/commit/351c4bda95ee40777b295a88bf26e69ef686d603))

## [1.28.11](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.10...backend-v1.28.11) (2026-04-09)


### Bug Fixes

* **metrics:** convert execution PnL to account currency and add quote currency display ([d97f333](https://github.com/yuyash/auto-forex-web-service/commit/d97f333a7b5a54eed2d4ce38973d949cd82310a7))
* **metrics:** convert execution PnL to account currency and add quote… ([#391](https://github.com/yuyash/auto-forex-web-service/issues/391)) ([d97f333](https://github.com/yuyash/auto-forex-web-service/commit/d97f333a7b5a54eed2d4ce38973d949cd82310a7))

## [1.28.10](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.9...backend-v1.28.10) (2026-04-08)


### Bug Fixes

* **strategy:** prevent cycle proliferation on TP re-entry ([#389](https://github.com/yuyash/auto-forex-web-service/issues/389)) ([7751d8b](https://github.com/yuyash/auto-forex-web-service/commit/7751d8b1586d311e9ed287a9dfd55b78e610074b))

## [1.28.9](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.8...backend-v1.28.9) (2026-04-08)


### Bug Fixes

* **frontend:** enable horizontal scroll on logs table for mobile ([#386](https://github.com/yuyash/auto-forex-web-service/issues/386)) ([ffc121f](https://github.com/yuyash/auto-forex-web-service/commit/ffc121fb5ee84eff25d237818fb9787fee5a84e2))

## [1.28.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.7...backend-v1.28.8) (2026-04-08)


### Bug Fixes

* **strategy:** preserve pending rebuilds when dynamic head hits TP ([#384](https://github.com/yuyash/auto-forex-web-service/issues/384)) ([00076ad](https://github.com/yuyash/auto-forex-web-service/commit/00076adf20381cc3a2aada717cc18ad093c732e4))

## [1.28.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.6...backend-v1.28.7) (2026-04-08)


### Bug Fixes

* **strategy:** correct cycle status, rebuild cycle assignment, and UI improvements ([#382](https://github.com/yuyash/auto-forex-web-service/issues/382)) ([ccceb5b](https://github.com/yuyash/auto-forex-web-service/commit/ccceb5be4efdf7d5c406aea6698b7c7968c52b8b))

## [1.28.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.5...backend-v1.28.6) (2026-04-08)


### Bug Fixes

* positions filter by execution ([#380](https://github.com/yuyash/auto-forex-web-service/issues/380)) ([1ad3464](https://github.com/yuyash/auto-forex-web-service/commit/1ad34649f578a92598a50d1f465468523b737caa))

## [1.28.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.4...backend-v1.28.5) (2026-04-07)


### Bug Fixes

* per metric yaxis width and hedging margin ([#376](https://github.com/yuyash/auto-forex-web-service/issues/376)) ([2e1dc96](https://github.com/yuyash/auto-forex-web-service/commit/2e1dc965239e31cb95455008aff6749c2eb4b5c1))

## [1.28.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.3...backend-v1.28.4) (2026-04-07)


### Bug Fixes

* snowball sl cycle completion and rebuild cleanup ([#372](https://github.com/yuyash/auto-forex-web-service/issues/372)) ([5485ebf](https://github.com/yuyash/auto-forex-web-service/commit/5485ebfac41b591c2fb040bdb2c4586a95153624))

## [1.28.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.2...backend-v1.28.3) (2026-04-07)


### Bug Fixes

* snowball close order violation with sl rebuild ([#370](https://github.com/yuyash/auto-forex-web-service/issues/370)) ([fbc6fa4](https://github.com/yuyash/auto-forex-web-service/commit/fbc6fa4b29cb83a33e1d506f7a102982c62a6181))

## [1.28.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.1...backend-v1.28.2) (2026-04-07)


### Bug Fixes

* **strategy:** resolve false close-order violation when SL rebuilds p… ([#368](https://github.com/yuyash/auto-forex-web-service/issues/368)) ([283fcd9](https://github.com/yuyash/auto-forex-web-service/commit/283fcd925d7168176daf6556d08cfd850ee8e58d))
* **strategy:** resolve false close-order violation when SL rebuilds produce coincident TPs ([283fcd9](https://github.com/yuyash/auto-forex-web-service/commit/283fcd925d7168176daf6556d08cfd850ee8e58d))

## [1.28.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.28.0...backend-v1.28.1) (2026-04-07)


### Bug Fixes

* **strategy:** swap LONG/SHORT rebuild conditions that were inverted ([#364](https://github.com/yuyash/auto-forex-web-service/issues/364)) ([20e6b30](https://github.com/yuyash/auto-forex-web-service/commit/20e6b3070fbeea140dd1f999e9cbba3a9e1da392))

## [1.28.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.5...backend-v1.28.0) (2026-04-07)


### Features

* **frontend:** i18n for close reasons and trade types, metrics chart improvements, stop-loss price fix ([aa20b7a](https://github.com/yuyash/auto-forex-web-service/commit/aa20b7a45b5b07e44073046c7520c9a085eab3da))
* **frontend:** i18n for close reasons and trade types, metrics chart… ([#361](https://github.com/yuyash/auto-forex-web-service/issues/361)) ([aa20b7a](https://github.com/yuyash/auto-forex-web-service/commit/aa20b7a45b5b07e44073046c7520c9a085eab3da))

## [1.27.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.4...backend-v1.27.5) (2026-04-06)


### Bug Fixes

* **backtest:** drain stale ticks from Redis channel on restart ([#352](https://github.com/yuyash/auto-forex-web-service/issues/352)) ([50f977d](https://github.com/yuyash/auto-forex-web-service/commit/50f977d4085508df183ea347207267b94ab57b4c))

## [1.27.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.3...backend-v1.27.4) (2026-04-06)


### Bug Fixes

* restart clear all execution data ([#348](https://github.com/yuyash/auto-forex-web-service/issues/348)) ([36f02f8](https://github.com/yuyash/auto-forex-web-service/commit/36f02f8375278bb201fc4386ce38243974eb8858))

## [1.27.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.2...backend-v1.27.3) (2026-04-05)


### Bug Fixes

* **trading:** correct layer and retracement numbering ([#342](https://github.com/yuyash/auto-forex-web-service/issues/342)) ([02e7d27](https://github.com/yuyash/auto-forex-web-service/commit/02e7d27ed950d733213e0896247b12aab6181afd))

## [1.27.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.1...backend-v1.27.2) (2026-04-05)


### Bug Fixes

* strategy trade margin label ([#336](https://github.com/yuyash/auto-forex-web-service/issues/336)) ([417588e](https://github.com/yuyash/auto-forex-web-service/commit/417588e94d157c015a8e82e9352e175842a81dd8))

## [1.27.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.27.0...backend-v1.27.1) (2026-04-05)


### Bug Fixes

* align config detail view with edit form layout and add i18n ([#334](https://github.com/yuyash/auto-forex-web-service/issues/334)) ([fd76d7c](https://github.com/yuyash/auto-forex-web-service/commit/fd76d7c1001f824fd80958bd9adddbf138740daf))

## [1.27.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.5...backend-v1.27.0) (2026-04-05)


### Features

* **trading:** add comprehensive metrics tracking and task data throt… ([#331](https://github.com/yuyash/auto-forex-web-service/issues/331)) ([40d2d8c](https://github.com/yuyash/auto-forex-web-service/commit/40d2d8c17b7dd28766f1ce6025484c7c2ed016cf))

## [1.26.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.4...backend-v1.26.5) (2026-04-05)


### Bug Fixes

* **shrink:** preserve last position in layer when upper layers have multiple ([#329](https://github.com/yuyash/auto-forex-web-service/issues/329)) ([be6516a](https://github.com/yuyash/auto-forex-web-service/commit/be6516a231b8afa030d55042635dcf9c060a4fcb))

## [1.26.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.3...backend-v1.26.4) (2026-04-05)


### Bug Fixes

* snowball unified position grid ([#327](https://github.com/yuyash/auto-forex-web-service/issues/327)) ([e135a58](https://github.com/yuyash/auto-forex-web-service/commit/e135a587dcfc2a1c29b8f4dd8f7a85d3c7ed0813))

## [1.26.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.2...backend-v1.26.3) (2026-04-04)


### Bug Fixes

* task lifecycle actions ([#325](https://github.com/yuyash/auto-forex-web-service/issues/325)) ([01fb643](https://github.com/yuyash/auto-forex-web-service/commit/01fb643907e33ca4a4af5fd10e9e58aab274afdf))

## [1.26.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.1...backend-v1.26.2) (2026-04-04)


### Bug Fixes

* shrink close order and reason ([#323](https://github.com/yuyash/auto-forex-web-service/issues/323)) ([9a5a59f](https://github.com/yuyash/auto-forex-web-service/commit/9a5a59f170e619c2da870bc8ab1c8e283e3b0b63))

## [1.26.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.26.0...backend-v1.26.1) (2026-04-04)


### Bug Fixes

* protection labels and margin ([#321](https://github.com/yuyash/auto-forex-web-service/issues/321)) ([47cc7cb](https://github.com/yuyash/auto-forex-web-service/commit/47cc7cb395aef6f3a8cb772fc505d5004a588473))

## [1.26.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.25.0...backend-v1.26.0) (2026-04-04)


### Features

* add metrics tab ([#319](https://github.com/yuyash/auto-forex-web-service/issues/319)) ([056bfe4](https://github.com/yuyash/auto-forex-web-service/commit/056bfe424c01465cede211b5a2954bc0ae9ce39c))

## [1.25.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.24.4...backend-v1.25.0) (2026-04-04)


### Features

* add shrink v2 ([#317](https://github.com/yuyash/auto-forex-web-service/issues/317)) ([a35f3bb](https://github.com/yuyash/auto-forex-web-service/commit/a35f3bbce8e6cc4e949ad3ec05cd62a352f58337))

## [1.24.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.24.3...backend-v1.24.4) (2026-04-03)


### Bug Fixes

* adverse pips from dict ([#315](https://github.com/yuyash/auto-forex-web-service/issues/315)) ([833eaf5](https://github.com/yuyash/auto-forex-web-service/commit/833eaf5d528ecdb791a7483b312a4cf3736c5829))

## [1.24.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.24.2...backend-v1.24.3) (2026-04-03)


### Bug Fixes

* **events:** restore actual_interval_pips in OpenPositionEvent.from_dict ([#313](https://github.com/yuyash/auto-forex-web-service/issues/313)) ([1edf654](https://github.com/yuyash/auto-forex-web-service/commit/1edf654165e2932fb67ab06a75d6c05fe0f5d6df))

## [1.24.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.24.1...backend-v1.24.2) (2026-04-03)


### Bug Fixes

* execution metrics snapshot ([#311](https://github.com/yuyash/auto-forex-web-service/issues/311)) ([ae3bfd0](https://github.com/yuyash/auto-forex-web-service/commit/ae3bfd0424340f00d87f166837af5e6582e7d3f6))

## [1.24.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.24.0...backend-v1.24.1) (2026-04-03)


### Bug Fixes

* table page sizes ([#309](https://github.com/yuyash/auto-forex-web-service/issues/309)) ([a3bc273](https://github.com/yuyash/auto-forex-web-service/commit/a3bc27389f71b0a86f0d9dae3220432abf221842))

## [1.24.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.23.1...backend-v1.24.0) (2026-04-02)


### Features

* Add --role-arn option to load-data command. ([a1c3a47](https://github.com/yuyash/auto-forex-web-service/commit/a1c3a47c963cf6780ea675a5baad04023c1e0e0f))
* add backtest export button and realized/unrealized P&L metrics to results tab ([6752c14](https://github.com/yuyash/auto-forex-web-service/commit/6752c14c30940641924703a6ad4ef0dac9064aed))
* add management commands for backtest, trading, and config CRUD … ([#54](https://github.com/yuyash/auto-forex-web-service/issues/54)) ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* add management commands for backtest, trading, and config CRUD operations ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* Add pip_size and instrument fields to backtest tasks and fix UI… ([#16](https://github.com/yuyash/auto-forex-web-service/issues/16)) ([5a71b6b](https://github.com/yuyash/auto-forex-web-service/commit/5a71b6b1ef624dc4367e224af29f4ca8e93d63ae))
* add snowball strategy ([#69](https://github.com/yuyash/auto-forex-web-service/issues/69)) ([e43eaef](https://github.com/yuyash/auto-forex-web-service/commit/e43eaefacd5a339b657a9e6348d3cc7f039019c0))
* add strategy defaults API and configuration UX improvements ([c69ce85](https://github.com/yuyash/auto-forex-web-service/commit/c69ce8558337f2af7f49a459d5fb5f61970768fe))
* add task summary API and migrate detail views to unified summary ([#35](https://github.com/yuyash/auto-forex-web-service/issues/35)) ([09e7bd8](https://github.com/yuyash/auto-forex-web-service/commit/09e7bd8112a7c67ad3186f25e47035368fae5975))
* add unified task results API + migrate UI; normalize equity curve ([b17367a](https://github.com/yuyash/auto-forex-web-service/commit/b17367abbff41483799c2d37a1dfbad9eb8500bc))
* **api:** migrate task execution APIs to execution_run_id ([#44](https://github.com/yuyash/auto-forex-web-service/issues/44)) ([b0d5332](https://github.com/yuyash/auto-forex-web-service/commit/b0d5332a5069aaa1fe038151926302f0485cf6be))
* **auth:** surface whitelist-blocked login failures ([64d7392](https://github.com/yuyash/auto-forex-web-service/commit/64d7392bee2645de932e7e39dd67211ec5580db5))
* auto-resume trading tasks on worker startup ([c1a1ce0](https://github.com/yuyash/auto-forex-web-service/commit/c1a1ce0dda811ebd3c9f22dec06aedb114f12258))
* celery resilience recovery ([#42](https://github.com/yuyash/auto-forex-web-service/issues/42)) ([dfd0f3f](https://github.com/yuyash/auto-forex-web-service/commit/dfd0f3fb5bdfd271927356d3bd07307adea27d55))
* **celery:** db backup s3 ([#154](https://github.com/yuyash/auto-forex-web-service/issues/154)) ([241bae4](https://github.com/yuyash/auto-forex-web-service/commit/241bae421ef664159a99245f963eeae879b9a400))
* event scope queue refactor ([#48](https://github.com/yuyash/auto-forex-web-service/issues/48)) ([220238c](https://github.com/yuyash/auto-forex-web-service/commit/220238c7497cb7f0602c1ba3b7d567bd3c657d29))
* **events:** enforce 1:1 canonical floor strategy events across backend+frontend ([4af619a](https://github.com/yuyash/auto-forex-web-service/commit/4af619a14a102916aad7a0ddde6e84a0573c67aa))
* **execution:** make reruns create executions + improve logs; hide non-layer chart labels. ([e1c96e5](https://github.com/yuyash/auto-forex-web-service/commit/e1c96e55f5817d5b9272078a95be5fde75b870a2))
* **floor:** default momentum to candle lookback ([d5b5f9c](https://github.com/yuyash/auto-forex-web-service/commit/d5b5f9c17921938ff624a94ef849aaa1e01299dd))
* hedging and trend panel ([#85](https://github.com/yuyash/auto-forex-web-service/issues/85)) ([8743b6a](https://github.com/yuyash/auto-forex-web-service/commit/8743b6ac2edf51f429039edb705dcbd8a2555154))
* historical execution viewer ([#274](https://github.com/yuyash/auto-forex-web-service/issues/274)) ([71517de](https://github.com/yuyash/auto-forex-web-service/commit/71517deed4aacb1c70a05250a576f84c7cd50c3a))
* improve market task logging ([#100](https://github.com/yuyash/auto-forex-web-service/issues/100)) ([3512d2d](https://github.com/yuyash/auto-forex-web-service/commit/3512d2dbcf3ac9a85561f734d29b2e03bbf5e3a8))
* layer initial entries ([#270](https://github.com/yuyash/auto-forex-web-service/issues/270)) ([de22012](https://github.com/yuyash/auto-forex-web-service/commit/de22012872123b96e545e86ab3de98113569b585))
* margin atr display progress padding ([#262](https://github.com/yuyash/auto-forex-web-service/issues/262)) ([282af2d](https://github.com/yuyash/auto-forex-web-service/commit/282af2d95a5d44a656a4d2075914801f857c12c8))
* refresh token security ([#51](https://github.com/yuyash/auto-forex-web-service/issues/51)) ([4eb53b4](https://github.com/yuyash/auto-forex-web-service/commit/4eb53b4bd67af15ffa5a9d3a6fc695e28612058f))
* snowball strategy tab design ([#137](https://github.com/yuyash/auto-forex-web-service/issues/137)) ([ef21bc0](https://github.com/yuyash/auto-forex-web-service/commit/ef21bc0b3f97b40f70722f4d937c57de6b67a513))
* strategy tab improvements ([#250](https://github.com/yuyash/auto-forex-web-service/issues/250)) ([5f60742](https://github.com/yuyash/auto-forex-web-service/commit/5f60742fe3d7e7ba0139c8df1634f95ba9e77952))
* **strategy:** add display cycle splitting and OHLC chart visualization ([#179](https://github.com/yuyash/auto-forex-web-service/issues/179)) ([20f97ab](https://github.com/yuyash/auto-forex-web-service/commit/20f97ab49f1f48126bf51cd35118b511b98e7192))
* task debug options ([#302](https://github.com/yuyash/auto-forex-web-service/issues/302)) ([be687eb](https://github.com/yuyash/auto-forex-web-service/commit/be687eb6d2a61a17e8150c6e5cd8bb5b6f3e37ce))
* **trading:** add planned_exit_price_formula to strategy events and … ([#96](https://github.com/yuyash/auto-forex-web-service/issues/96)) ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** add planned_exit_price_formula to strategy events and improve mobile UI ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** add sequence_number to preserve event ordering within … ([#206](https://github.com/yuyash/auto-forex-web-service/issues/206)) ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))
* **trading:** add sequence_number to preserve event ordering within same tick ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))
* **trading:** enforce page/page_size pagination across logs & results endpoints ([2d66aad](https://github.com/yuyash/auto-forex-web-service/commit/2d66aad0f6b9b40f133fff5e5ae42388fbeb1f90))
* **trading:** improve trading system with enhanced events, positions, and UI components ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading system with enhanced events, positions… ([#91](https://github.com/yuyash/auto-forex-web-service/issues/91)) ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading UI and backend execution handling ([#93](https://github.com/yuyash/auto-forex-web-service/issues/93)) ([48ebe50](https://github.com/yuyash/auto-forex-web-service/commit/48ebe50cf5015546d37629ce32fa10b1f0011e46))
* **trading:** persist live execution artifacts + metrics checkpoints ([a6b8c8d](https://github.com/yuyash/auto-forex-web-service/commit/a6b8c8d1516a42b171b4dac8a688f489274eae88))
* **trading:** refactor app structure ([#21](https://github.com/yuyash/auto-forex-web-service/issues/21)) ([6e5db34](https://github.com/yuyash/auto-forex-web-service/commit/6e5db3461377af6596b6e1e5c6b8ce4c5df1eddb))


### Bug Fixes

* add version info ([#27](https://github.com/yuyash/auto-forex-web-service/issues/27)) ([b5217d1](https://github.com/yuyash/auto-forex-web-service/commit/b5217d16a4e476825b5521db9fe1d53c2fe9093a))
* api enhancement ([#40](https://github.com/yuyash/auto-forex-web-service/issues/40)) ([ab0b564](https://github.com/yuyash/auto-forex-web-service/commit/ab0b564dd6589279ed84556ba586d64e01dfb60d))
* **auth:** add AnonRateThrottle to protect unauthenticated endpoints ([#56](https://github.com/yuyash/auto-forex-web-service/issues/56)) ([ae490ce](https://github.com/yuyash/auto-forex-web-service/commit/ae490ce1128b01d2b143c90f98570adc8780dae1))
* **backtest:** make charts and markers robust ([25013aa](https://github.com/yuyash/auto-forex-web-service/commit/25013aa50742b17feb59d019843ac4a32d2b2f8c))
* celery task doesnt update the progress correctly. ([f14f3f2](https://github.com/yuyash/auto-forex-web-service/commit/f14f3f202d459ea599bea27ce89155b6a5e5db59))
* celery task race condition ([#31](https://github.com/yuyash/auto-forex-web-service/issues/31)) ([87b3354](https://github.com/yuyash/auto-forex-web-service/commit/87b33548f2cb0c52ad1aa4a2b250944ec8e707da))
* **celery:** remove max-tasks-per-child and add shutdown logging ([#298](https://github.com/yuyash/auto-forex-web-service/issues/298)) ([22318b7](https://github.com/yuyash/auto-forex-web-service/commit/22318b7698ac4034c2a2112e29ceb5ce52e9649e))
* chart marker positions ([#197](https://github.com/yuyash/auto-forex-web-service/issues/197)) ([a9794a3](https://github.com/yuyash/auto-forex-web-service/commit/a9794a331f766c403e76d6e294c262943f8f4d66))
* **chart:** fixed an issue where OHLC chart doesn't follow the progre… ([#120](https://github.com/yuyash/auto-forex-web-service/issues/120)) ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** fixed an issue where OHLC chart doesn't follow the progress bar properly. ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** trading migration 0019 ([#116](https://github.com/yuyash/auto-forex-web-service/issues/116)) ([a8d9a4e](https://github.com/yuyash/auto-forex-web-service/commit/a8d9a4e7d931c2106f4b643bef05a70f6e7e133c))
* clear stale stream cache on startup ([cc65f57](https://github.com/yuyash/auto-forex-web-service/commit/cc65f57a8190bf7ab95151984b07515783eb959b))
* cycle based snowball strategy ([#188](https://github.com/yuyash/auto-forex-web-service/issues/188)) ([4cbd2be](https://github.com/yuyash/auto-forex-web-service/commit/4cbd2be327178526c0828d871bc77c43e31a05de))
* cycle id assignment and chart ([#190](https://github.com/yuyash/auto-forex-web-service/issues/190)) ([d3f7700](https://github.com/yuyash/auto-forex-web-service/commit/d3f77005565781c4b3629d3f12bfc3d9b542b9d4))
* disable backup and Athena jobs ([#224](https://github.com/yuyash/auto-forex-web-service/issues/224)) ([044d78f](https://github.com/yuyash/auto-forex-web-service/commit/044d78f9e5177380a10daed64f03e59a2c7d1d76))
* **docker:** prevent prod config bind-mount shadowing Django settings. ([b3270b1](https://github.com/yuyash/auto-forex-web-service/commit/b3270b1b11bfd83869950037656d8cd752eb04ce))
* enforce frontend npm ci and override blocked react-is ([#46](https://github.com/yuyash/auto-forex-web-service/issues/46)) ([1f200b4](https://github.com/yuyash/auto-forex-web-service/commit/1f200b475d5bedc8de79256ec03b19f5a651c877))
* **floor-strategy:** reset retracement flag when price continues moving against position ([e88207b](https://github.com/yuyash/auto-forex-web-service/commit/e88207bc09c890e6f575696c7a49416048838caa))
* **frontend:** OANDA accounts UX improvements ([#244](https://github.com/yuyash/auto-forex-web-service/issues/244)) ([f14db1b](https://github.com/yuyash/auto-forex-web-service/commit/f14db1b22aab2f296203f66294e5833f24f28080))
* handle immutable ExecutionMetrics for trading tasks ([9a39233](https://github.com/yuyash/auto-forex-web-service/commit/9a392333e83ec398185ec5754a67825778c1f127))
* Handle new OANDA API message types for streaming ([47f7d25](https://github.com/yuyash/auto-forex-web-service/commit/47f7d2504b39648f87561f07483255229bbefa13))
* incremental polling reduce backend load ([#24](https://github.com/yuyash/auto-forex-web-service/issues/24)) ([980f163](https://github.com/yuyash/auto-forex-web-service/commit/980f1637145586a6955bfdb434532fcd1ed1b3e7))
* limit live results and strategy events to prevent 1GB+ JSON payloads ([61c4477](https://github.com/yuyash/auto-forex-web-service/commit/61c4477ea1f1fc846f08ea3207185e420c5a623e))
* **logging:** improve production logging ([#106](https://github.com/yuyash/auto-forex-web-service/issues/106)) ([06f2fdb](https://github.com/yuyash/auto-forex-web-service/commit/06f2fdb068dda50fba59a72312a3be4e11bf4940))
* **market-data:** use correct OANDA streaming hostname. ([af6e392](https://github.com/yuyash/auto-forex-web-service/commit/af6e39257d6a25f99bac766deeca239a318a39dc))
* **market:** dedupe TickData bulk upserts to avoid Postgres cardinality violation ([397a45c](https://github.com/yuyash/auto-forex-web-service/commit/397a45c44561af2636297d6b2b6295f35488b400))
* **market:** increase OANDA candle API timeout and handle V20Timeout … ([#246](https://github.com/yuyash/auto-forex-web-service/issues/246)) ([1dccc0b](https://github.com/yuyash/auto-forex-web-service/commit/1dccc0b08921928d69d6f623d2e312f949149296))
* **market:** increase OANDA candle API timeout and handle V20Timeout gracefully ([1dccc0b](https://github.com/yuyash/auto-forex-web-service/commit/1dccc0b08921928d69d6f623d2e312f949149296))
* **metrics:** resolve overlay display and add viewport-driven fetching ([#114](https://github.com/yuyash/auto-forex-web-service/issues/114)) ([e87a285](https://github.com/yuyash/auto-forex-web-service/commit/e87a2855b4ccf087d42cf4d4f876a48c73737a24))
* minor issues ([#219](https://github.com/yuyash/auto-forex-web-service/issues/219)) ([e217380](https://github.com/yuyash/auto-forex-web-service/commit/e2173802d95d68d7223d1b1abe2dde3ec6e42a5a))
* oanda error propagation ([#248](https://github.com/yuyash/auto-forex-web-service/issues/248)) ([8d90bc6](https://github.com/yuyash/auto-forex-web-service/commit/8d90bc61a40fc07af1b3f161e8febca62e910ebb))
* **orders:** change broker_order_id from CharField(255) to TextField ([#104](https://github.com/yuyash/auto-forex-web-service/issues/104)) ([8f16ec6](https://github.com/yuyash/auto-forex-web-service/commit/8f16ec6a76955d4b4fc26488dfe75b71aaa78534))
* prevent retracement_limit_reached spam generating 167K+ events ([6c14968](https://github.com/yuyash/auto-forex-web-service/commit/6c149681e55eee083914f78a2acca8f625e3a2cc))
* read version from pyproject.toml instead of importlib.metadata ([#29](https://github.com/yuyash/auto-forex-web-service/issues/29)) ([8a8f986](https://github.com/yuyash/auto-forex-web-service/commit/8a8f986a5c5ae0433cb8c5ca24c339f13e4d29ad))
* reduce API rate limit pressure and lazy-load chart data ([#38](https://github.com/yuyash/auto-forex-web-service/issues/38)) ([e733834](https://github.com/yuyash/auto-forex-web-service/commit/e733834e6bf47bd144d98d9c526f5a5eceb19745))
* remove layer on initial close ([#294](https://github.com/yuyash/auto-forex-web-service/issues/294)) ([6b7c4a5](https://github.com/yuyash/auto-forex-web-service/commit/6b7c4a563a0105a1dedd39115e35ee3f220c97ce))
* resolve all ty type checker errors and warnings ([#13](https://github.com/yuyash/auto-forex-web-service/issues/13)) ([1883525](https://github.com/yuyash/auto-forex-web-service/commit/1883525ce1fd5008b5c46d42e57d185620a78502))
* resolve backend code quality issues ([#160](https://github.com/yuyash/auto-forex-web-service/issues/160)) ([def2e22](https://github.com/yuyash/auto-forex-web-service/commit/def2e22766e4192779932619406516f10ffc42b6))
* resolve flake8, mypy, and pylint errors in floor strategy and task executor ([b2b9949](https://github.com/yuyash/auto-forex-web-service/commit/b2b9949c5408ccbc163fdf92abd249b55f0ca88d))
* **security:** remove unused UserSession.last_activity field ([#112](https://github.com/yuyash/auto-forex-web-service/issues/112)) ([3198e40](https://github.com/yuyash/auto-forex-web-service/commit/3198e40782bf16ffe27a35c5e04c53854fb6f068))
* snowball add count reset and tests ([#73](https://github.com/yuyash/auto-forex-web-service/issues/73)) ([847ffd9](https://github.com/yuyash/auto-forex-web-service/commit/847ffd9cef2929009549f418acfb95541d11ea97))
* snowball layer reset on initial tp ([#285](https://github.com/yuyash/auto-forex-web-service/issues/285)) ([4cb0270](https://github.com/yuyash/auto-forex-web-service/commit/4cb0270928e0bec6856ef91ca0867ed9d459c071))
* snowball strategy logic ([#272](https://github.com/yuyash/auto-forex-web-service/issues/272)) ([7c20257](https://github.com/yuyash/auto-forex-web-service/commit/7c202571f6bdd977d4f0286a18b74a95f1097831))
* snowball weighted avg layer rename ([#266](https://github.com/yuyash/auto-forex-web-service/issues/266)) ([f2e817f](https://github.com/yuyash/auto-forex-web-service/commit/f2e817f34386f42d3f6a86370cbed8656d2bd711))
* **snowball:** guard L1/R0 close when counter entries are open ([#306](https://github.com/yuyash/auto-forex-web-service/issues/306)) ([2f92032](https://github.com/yuyash/auto-forex-web-service/commit/2f92032447ce1ad5cd84da2438f0bbd3bdfb022a))
* **snowball:** reset layer instead of completing it when layer-initia… ([#280](https://github.com/yuyash/auto-forex-web-service/issues/280)) ([1e7e9db](https://github.com/yuyash/auto-forex-web-service/commit/1e7e9dbe21f255bc45a89dc0032666d29cfaec1e))
* **snowball:** reset layer instead of completing it when layer-initial TP closes ([1e7e9db](https://github.com/yuyash/auto-forex-web-service/commit/1e7e9dbe21f255bc45a89dc0032666d29cfaec1e))
* **snowball:** use prev layer highest slot close price for layer initial TP ([#290](https://github.com/yuyash/auto-forex-web-service/issues/290)) ([8428ebe](https://github.com/yuyash/auto-forex-web-service/commit/8428ebef294d968db2d1961d0d3aece667f96517))
* sort execution list by created_at and show execution ID in overview ([#286](https://github.com/yuyash/auto-forex-web-service/issues/286)) ([8bfbc6e](https://github.com/yuyash/auto-forex-web-service/commit/8bfbc6eced95b0149a61bfe5cfcb490292fd33ed))
* stabilize rerun/status flow and fix floor trade PnL metrics ([d7f2325](https://github.com/yuyash/auto-forex-web-service/commit/d7f23254fef3c23c2f79e48732ef255f68ca6219))
* stabilize streams, logs, and backtest/trading results UI ([f6f15a2](https://github.com/yuyash/auto-forex-web-service/commit/f6f15a241fda3c57ca995472e6de429e64b63ef5))
* strategy events root entry id default ([#163](https://github.com/yuyash/auto-forex-web-service/issues/163)) ([523e8a6](https://github.com/yuyash/auto-forex-web-service/commit/523e8a6ab3162e2eef92be0e2002f89c232d3e48))
* strategy grouping parent chain ([#175](https://github.com/yuyash/auto-forex-web-service/issues/175)) ([19461d6](https://github.com/yuyash/auto-forex-web-service/commit/19461d62e3d0329d3d3360142eb206b8ee9ff944))
* strategy tab detail manual refresh ([#292](https://github.com/yuyash/auto-forex-web-service/issues/292)) ([eb58ab5](https://github.com/yuyash/auto-forex-web-service/commit/eb58ab5e283cc58880b4d0daf617440d10286f1d))
* **strategy:** correct snowball counter lot sizing and add retracemen… ([#87](https://github.com/yuyash/auto-forex-web-service/issues/87)) ([804e7d1](https://github.com/yuyash/auto-forex-web-service/commit/804e7d15754e8a6310dd3a03201ed805b1f327f2))
* **strategy:** DB fallback for cycle_id, granularity selector, chart … ([#204](https://github.com/yuyash/auto-forex-web-service/issues/204)) ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))
* **strategy:** DB fallback for cycle_id, granularity selector, chart fixes ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))
* **strategy:** guard m_pips range validation behind dynamic_tp_enable… ([#81](https://github.com/yuyash/auto-forex-web-service/issues/81)) ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** guard m_pips range validation behind dynamic_tp_enabled and raise m_pips_max default ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** normalize atr_timeframe to uppercase and add snowball … ([#75](https://github.com/yuyash/auto-forex-web-service/issues/75)) ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **strategy:** normalize atr_timeframe to uppercase and add snowball tests ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **strategy:** trigger deployment for cycle-based snowball refactor ([#182](https://github.com/yuyash/auto-forex-web-service/issues/182)) ([13f6bc4](https://github.com/yuyash/auto-forex-web-service/commit/13f6bc43549cb8b1d359516a8c9590df142c9306))
* **tests:** update expected hostnames for streaming tests ([cbaa7a2](https://github.com/yuyash/auto-forex-web-service/commit/cbaa7a27039043ae9687813829ced34e0ccf33fe))
* trading task initial balance and default instrument ([#242](https://github.com/yuyash/auto-forex-web-service/issues/242)) ([3cc01e8](https://github.com/yuyash/auto-forex-web-service/commit/3cc01e899f3ea467382f9462ff1536162996d0f9))
* **trading:** add instrument selector to trading task creation form ([#240](https://github.com/yuyash/auto-forex-web-service/issues/240)) ([5f1220e](https://github.com/yuyash/auto-forex-web-service/commit/5f1220ecbd6c6da2516d33ac5065d96d5993a6bf))
* **trading:** change planned_exit_price_formula from CharField to Tex… ([#226](https://github.com/yuyash/auto-forex-web-service/issues/226)) ([53d8370](https://github.com/yuyash/auto-forex-web-service/commit/53d8370a42bd6339fa2775a12d78aee2b146db7a))
* **trading:** change planned_exit_price_formula from CharField to TextField ([53d8370](https://github.com/yuyash/auto-forex-web-service/commit/53d8370a42bd6339fa2775a12d78aee2b146db7a))
* **trading:** fix position cache memory leak and add celery mem_limit ([#300](https://github.com/yuyash/auto-forex-web-service/issues/300)) ([9fabcc1](https://github.com/yuyash/auto-forex-web-service/commit/9fabcc1f2342b6a42b39b650f9d13716939fb2ef))
* **trading:** trading task creation ([#125](https://github.com/yuyash/auto-forex-web-service/issues/125)) ([74f1dbd](https://github.com/yuyash/auto-forex-web-service/commit/74f1dbd177acef2936fd8d0a1245c93c58a84be2))
* **trading:** use pure arithmetic in planned_exit_price_formula ([#98](https://github.com/yuyash/auto-forex-web-service/issues/98)) ([0b5edbd](https://github.com/yuyash/auto-forex-web-service/commit/0b5edbdeb05c6fc0fab1be041bbee75fb4cc3011))
* trigger deployment ([#169](https://github.com/yuyash/auto-forex-web-service/issues/169)) ([9d3cafd](https://github.com/yuyash/auto-forex-web-service/commit/9d3cafd7bbcfea767429c7313dceb9a0e33806bc))
* Use decrypted API token for OANDA streaming connections ([aa9ead5](https://github.com/yuyash/auto-forex-web-service/commit/aa9ead51e80b0930655e71f54b60f5dba5c0bbd9))
* vscode settings warnings ([#134](https://github.com/yuyash/auto-forex-web-service/issues/134)) ([c55842d](https://github.com/yuyash/auto-forex-web-service/commit/c55842d4b25147605c7e480afe08a2259d6cf728))


### Refactoring

* bid/ask execution, pip metadata, and account detail UX ([fcbf9dd](https://github.com/yuyash/auto-forex-web-service/commit/fcbf9dd6368670b806fd9ad702a1f9c819d69ce6))
* deduplicate task lifecycle, remove dead auth checks, add copy endpoint ([#146](https://github.com/yuyash/auto-forex-web-service/issues/146)) ([cef883e](https://github.com/yuyash/auto-forex-web-service/commit/cef883e8775c07e6f95d745fc887016e4eeb4f8d))
* implement core trading system infrastructure ([#17](https://github.com/yuyash/auto-forex-web-service/issues/17)) ([f0657aa](https://github.com/yuyash/auto-forex-web-service/commit/f0657aa1c6f1e8b695840c0cd89fd7ed7f277870))
* implement core trading system infrastructure (tasks 1-7) ([f0657aa](https://github.com/yuyash/auto-forex-web-service/commit/f0657aa1c6f1e8b695840c0cd89fd7ed7f277870))
* **metrics:** replace tick-level writes with minute-level aggreg… ([#110](https://github.com/yuyash/auto-forex-web-service/issues/110)) ([46a97a0](https://github.com/yuyash/auto-forex-web-service/commit/46a97a07db27d6b036b4bdc8a88ea1e30d0f08d5))
* **metrics:** replace tick-level writes with minute-level aggregation ([46a97a0](https://github.com/yuyash/auto-forex-web-service/commit/46a97a07db27d6b036b4bdc8a88ea1e30d0f08d5))
* refresh trading config and frontend tests ([a9735b1](https://github.com/yuyash/auto-forex-web-service/commit/a9735b1434f5d375c1f5644d64b4c0293b86a508))
* snowball layer retracement model ([#276](https://github.com/yuyash/auto-forex-web-service/issues/276)) ([47376d7](https://github.com/yuyash/auto-forex-web-service/commit/47376d7f49fde392a19fc852ac321668ac89decb))
* snowball layer retracement model ([#278](https://github.com/yuyash/auto-forex-web-service/issues/278)) ([e0907a1](https://github.com/yuyash/auto-forex-web-service/commit/e0907a1dfa0d16a629524d7b495e0bb22afa41c2))
* snowball layer retracement model ([#283](https://github.com/yuyash/auto-forex-web-service/issues/283)) ([0696ff8](https://github.com/yuyash/auto-forex-web-service/commit/0696ff8e8aa48fce7175737433fd66adb2616f68))
* snowball rules overhaul ([#288](https://github.com/yuyash/auto-forex-web-service/issues/288)) ([3f7bffb](https://github.com/yuyash/auto-forex-web-service/commit/3f7bffba0c559af8211ac4fc8f3dcb8f8a398f92))
* **strategy:** cycle-based snowball architecture with Trade.cycl… ([#181](https://github.com/yuyash/auto-forex-web-service/issues/181)) ([6f786b9](https://github.com/yuyash/auto-forex-web-service/commit/6f786b9a1b1bbd0e6b024096156974761107dee3))
* **strategy:** cycle-based snowball architecture with Trade.cycle_id ([6f786b9](https://github.com/yuyash/auto-forex-web-service/commit/6f786b9a1b1bbd0e6b024096156974761107dee3))
* **strategy:** improve snowball strategy parameter configuration ([#71](https://github.com/yuyash/auto-forex-web-service/issues/71)) ([27d49ed](https://github.com/yuyash/auto-forex-web-service/commit/27d49ed4c1be81d7bc5bbffad0b9774efbcd6dc7))

## [1.23.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.23.0...backend-v1.23.1) (2026-04-02)


### Bug Fixes

* **snowball:** guard L1/R0 close when counter entries are open ([#306](https://github.com/yuyash/auto-forex-web-service/issues/306)) ([2f92032](https://github.com/yuyash/auto-forex-web-service/commit/2f92032447ce1ad5cd84da2438f0bbd3bdfb022a))

## [1.23.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.11...backend-v1.23.0) (2026-04-02)


### Features

* task debug options ([#302](https://github.com/yuyash/auto-forex-web-service/issues/302)) ([be687eb](https://github.com/yuyash/auto-forex-web-service/commit/be687eb6d2a61a17e8150c6e5cd8bb5b6f3e37ce))

## [1.22.11](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.10...backend-v1.22.11) (2026-04-02)


### Bug Fixes

* **trading:** fix position cache memory leak and add celery mem_limit ([#300](https://github.com/yuyash/auto-forex-web-service/issues/300)) ([9fabcc1](https://github.com/yuyash/auto-forex-web-service/commit/9fabcc1f2342b6a42b39b650f9d13716939fb2ef))

## [1.22.10](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.9...backend-v1.22.10) (2026-04-02)


### Bug Fixes

* **celery:** remove max-tasks-per-child and add shutdown logging ([#298](https://github.com/yuyash/auto-forex-web-service/issues/298)) ([22318b7](https://github.com/yuyash/auto-forex-web-service/commit/22318b7698ac4034c2a2112e29ceb5ce52e9649e))

## [1.22.9](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.8...backend-v1.22.9) (2026-04-02)


### Bug Fixes

* remove layer on initial close ([#294](https://github.com/yuyash/auto-forex-web-service/issues/294)) ([6b7c4a5](https://github.com/yuyash/auto-forex-web-service/commit/6b7c4a563a0105a1dedd39115e35ee3f220c97ce))

## [1.22.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.7...backend-v1.22.8) (2026-04-01)


### Bug Fixes

* strategy tab detail manual refresh ([#292](https://github.com/yuyash/auto-forex-web-service/issues/292)) ([eb58ab5](https://github.com/yuyash/auto-forex-web-service/commit/eb58ab5e283cc58880b4d0daf617440d10286f1d))

## [1.22.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.6...backend-v1.22.7) (2026-04-01)


### Bug Fixes

* **snowball:** use prev layer highest slot close price for layer initial TP ([#290](https://github.com/yuyash/auto-forex-web-service/issues/290)) ([8428ebe](https://github.com/yuyash/auto-forex-web-service/commit/8428ebef294d968db2d1961d0d3aece667f96517))

## [1.22.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.5...backend-v1.22.6) (2026-04-01)


### Refactoring

* snowball rules overhaul ([#288](https://github.com/yuyash/auto-forex-web-service/issues/288)) ([3f7bffb](https://github.com/yuyash/auto-forex-web-service/commit/3f7bffba0c559af8211ac4fc8f3dcb8f8a398f92))

## [1.22.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.4...backend-v1.22.5) (2026-04-01)


### Bug Fixes

* snowball layer reset on initial tp ([#285](https://github.com/yuyash/auto-forex-web-service/issues/285)) ([4cb0270](https://github.com/yuyash/auto-forex-web-service/commit/4cb0270928e0bec6856ef91ca0867ed9d459c071))
* sort execution list by created_at and show execution ID in overview ([#286](https://github.com/yuyash/auto-forex-web-service/issues/286)) ([8bfbc6e](https://github.com/yuyash/auto-forex-web-service/commit/8bfbc6eced95b0149a61bfe5cfcb490292fd33ed))

## [1.22.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.3...backend-v1.22.4) (2026-04-01)


### Refactoring

* snowball layer retracement model ([#283](https://github.com/yuyash/auto-forex-web-service/issues/283)) ([0696ff8](https://github.com/yuyash/auto-forex-web-service/commit/0696ff8e8aa48fce7175737433fd66adb2616f68))

## [1.22.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.2...backend-v1.22.3) (2026-04-01)


### Bug Fixes

* **snowball:** reset layer instead of completing it when layer-initia… ([#280](https://github.com/yuyash/auto-forex-web-service/issues/280)) ([1e7e9db](https://github.com/yuyash/auto-forex-web-service/commit/1e7e9dbe21f255bc45a89dc0032666d29cfaec1e))
* **snowball:** reset layer instead of completing it when layer-initial TP closes ([1e7e9db](https://github.com/yuyash/auto-forex-web-service/commit/1e7e9dbe21f255bc45a89dc0032666d29cfaec1e))

## [1.22.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.1...backend-v1.22.2) (2026-04-01)


### Refactoring

* snowball layer retracement model ([#278](https://github.com/yuyash/auto-forex-web-service/issues/278)) ([e0907a1](https://github.com/yuyash/auto-forex-web-service/commit/e0907a1dfa0d16a629524d7b495e0bb22afa41c2))

## [1.22.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.22.0...backend-v1.22.1) (2026-03-31)


### Refactoring

* snowball layer retracement model ([#276](https://github.com/yuyash/auto-forex-web-service/issues/276)) ([47376d7](https://github.com/yuyash/auto-forex-web-service/commit/47376d7f49fde392a19fc852ac321668ac89decb))

## [1.22.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.21.1...backend-v1.22.0) (2026-03-31)


### Features

* historical execution viewer ([#274](https://github.com/yuyash/auto-forex-web-service/issues/274)) ([71517de](https://github.com/yuyash/auto-forex-web-service/commit/71517deed4aacb1c70a05250a576f84c7cd50c3a))

## [1.21.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.21.0...backend-v1.21.1) (2026-03-31)


### Bug Fixes

* snowball strategy logic ([#272](https://github.com/yuyash/auto-forex-web-service/issues/272)) ([7c20257](https://github.com/yuyash/auto-forex-web-service/commit/7c202571f6bdd977d4f0286a18b74a95f1097831))

## [1.21.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.20.1...backend-v1.21.0) (2026-03-30)


### Features

* layer initial entries ([#270](https://github.com/yuyash/auto-forex-web-service/issues/270)) ([de22012](https://github.com/yuyash/auto-forex-web-service/commit/de22012872123b96e545e86ab3de98113569b585))

## [1.20.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.20.0...backend-v1.20.1) (2026-03-30)


### Bug Fixes

* snowball weighted avg layer rename ([#266](https://github.com/yuyash/auto-forex-web-service/issues/266)) ([f2e817f](https://github.com/yuyash/auto-forex-web-service/commit/f2e817f34386f42d3f6a86370cbed8656d2bd711))

## [1.20.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.19.0...backend-v1.20.0) (2026-03-29)


### Features

* margin atr display progress padding ([#262](https://github.com/yuyash/auto-forex-web-service/issues/262)) ([282af2d](https://github.com/yuyash/auto-forex-web-service/commit/282af2d95a5d44a656a4d2075914801f857c12c8))

## [1.19.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.8...backend-v1.19.0) (2026-03-28)


### Features

* strategy tab improvements ([#250](https://github.com/yuyash/auto-forex-web-service/issues/250)) ([5f60742](https://github.com/yuyash/auto-forex-web-service/commit/5f60742fe3d7e7ba0139c8df1634f95ba9e77952))

## [1.18.8](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.7...backend-v1.18.8) (2026-03-28)


### Bug Fixes

* oanda error propagation ([#248](https://github.com/yuyash/auto-forex-web-service/issues/248)) ([8d90bc6](https://github.com/yuyash/auto-forex-web-service/commit/8d90bc61a40fc07af1b3f161e8febca62e910ebb))

## [1.18.7](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.6...backend-v1.18.7) (2026-03-27)


### Bug Fixes

* **market:** increase OANDA candle API timeout and handle V20Timeout … ([#246](https://github.com/yuyash/auto-forex-web-service/issues/246)) ([1dccc0b](https://github.com/yuyash/auto-forex-web-service/commit/1dccc0b08921928d69d6f623d2e312f949149296))
* **market:** increase OANDA candle API timeout and handle V20Timeout gracefully ([1dccc0b](https://github.com/yuyash/auto-forex-web-service/commit/1dccc0b08921928d69d6f623d2e312f949149296))

## [1.18.6](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.5...backend-v1.18.6) (2026-03-27)


### Bug Fixes

* **frontend:** OANDA accounts UX improvements ([#244](https://github.com/yuyash/auto-forex-web-service/issues/244)) ([f14db1b](https://github.com/yuyash/auto-forex-web-service/commit/f14db1b22aab2f296203f66294e5833f24f28080))

## [1.18.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.4...backend-v1.18.5) (2026-03-27)


### Bug Fixes

* trading task initial balance and default instrument ([#242](https://github.com/yuyash/auto-forex-web-service/issues/242)) ([3cc01e8](https://github.com/yuyash/auto-forex-web-service/commit/3cc01e899f3ea467382f9462ff1536162996d0f9))

## [1.18.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.3...backend-v1.18.4) (2026-03-27)


### Bug Fixes

* **trading:** add instrument selector to trading task creation form ([#240](https://github.com/yuyash/auto-forex-web-service/issues/240)) ([5f1220e](https://github.com/yuyash/auto-forex-web-service/commit/5f1220ecbd6c6da2516d33ac5065d96d5993a6bf))

## [1.18.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.2...backend-v1.18.3) (2026-03-27)


### Bug Fixes

* **trading:** change planned_exit_price_formula from CharField to Tex… ([#226](https://github.com/yuyash/auto-forex-web-service/issues/226)) ([53d8370](https://github.com/yuyash/auto-forex-web-service/commit/53d8370a42bd6339fa2775a12d78aee2b146db7a))
* **trading:** change planned_exit_price_formula from CharField to TextField ([53d8370](https://github.com/yuyash/auto-forex-web-service/commit/53d8370a42bd6339fa2775a12d78aee2b146db7a))

## [1.18.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.1...backend-v1.18.2) (2026-03-27)


### Bug Fixes

* disable backup and Athena jobs ([#224](https://github.com/yuyash/auto-forex-web-service/issues/224)) ([044d78f](https://github.com/yuyash/auto-forex-web-service/commit/044d78f9e5177380a10daed64f03e59a2c7d1d76))

## [1.18.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.18.0...backend-v1.18.1) (2026-03-27)


### Bug Fixes

* minor issues ([#219](https://github.com/yuyash/auto-forex-web-service/issues/219)) ([e217380](https://github.com/yuyash/auto-forex-web-service/commit/e2173802d95d68d7223d1b1abe2dde3ec6e42a5a))

## [1.18.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.17.0...backend-v1.18.0) (2026-03-26)


### Features

* Add --role-arn option to load-data command. ([a1c3a47](https://github.com/yuyash/auto-forex-web-service/commit/a1c3a47c963cf6780ea675a5baad04023c1e0e0f))
* add backtest export button and realized/unrealized P&L metrics to results tab ([6752c14](https://github.com/yuyash/auto-forex-web-service/commit/6752c14c30940641924703a6ad4ef0dac9064aed))
* add management commands for backtest, trading, and config CRUD … ([#54](https://github.com/yuyash/auto-forex-web-service/issues/54)) ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* add management commands for backtest, trading, and config CRUD operations ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* Add pip_size and instrument fields to backtest tasks and fix UI… ([#16](https://github.com/yuyash/auto-forex-web-service/issues/16)) ([5a71b6b](https://github.com/yuyash/auto-forex-web-service/commit/5a71b6b1ef624dc4367e224af29f4ca8e93d63ae))
* add snowball strategy ([#69](https://github.com/yuyash/auto-forex-web-service/issues/69)) ([e43eaef](https://github.com/yuyash/auto-forex-web-service/commit/e43eaefacd5a339b657a9e6348d3cc7f039019c0))
* add strategy defaults API and configuration UX improvements ([c69ce85](https://github.com/yuyash/auto-forex-web-service/commit/c69ce8558337f2af7f49a459d5fb5f61970768fe))
* add task summary API and migrate detail views to unified summary ([#35](https://github.com/yuyash/auto-forex-web-service/issues/35)) ([09e7bd8](https://github.com/yuyash/auto-forex-web-service/commit/09e7bd8112a7c67ad3186f25e47035368fae5975))
* add unified task results API + migrate UI; normalize equity curve ([b17367a](https://github.com/yuyash/auto-forex-web-service/commit/b17367abbff41483799c2d37a1dfbad9eb8500bc))
* **api:** migrate task execution APIs to execution_run_id ([#44](https://github.com/yuyash/auto-forex-web-service/issues/44)) ([b0d5332](https://github.com/yuyash/auto-forex-web-service/commit/b0d5332a5069aaa1fe038151926302f0485cf6be))
* **auth:** surface whitelist-blocked login failures ([64d7392](https://github.com/yuyash/auto-forex-web-service/commit/64d7392bee2645de932e7e39dd67211ec5580db5))
* auto-resume trading tasks on worker startup ([c1a1ce0](https://github.com/yuyash/auto-forex-web-service/commit/c1a1ce0dda811ebd3c9f22dec06aedb114f12258))
* celery resilience recovery ([#42](https://github.com/yuyash/auto-forex-web-service/issues/42)) ([dfd0f3f](https://github.com/yuyash/auto-forex-web-service/commit/dfd0f3fb5bdfd271927356d3bd07307adea27d55))
* **celery:** db backup s3 ([#154](https://github.com/yuyash/auto-forex-web-service/issues/154)) ([241bae4](https://github.com/yuyash/auto-forex-web-service/commit/241bae421ef664159a99245f963eeae879b9a400))
* event scope queue refactor ([#48](https://github.com/yuyash/auto-forex-web-service/issues/48)) ([220238c](https://github.com/yuyash/auto-forex-web-service/commit/220238c7497cb7f0602c1ba3b7d567bd3c657d29))
* **events:** enforce 1:1 canonical floor strategy events across backend+frontend ([4af619a](https://github.com/yuyash/auto-forex-web-service/commit/4af619a14a102916aad7a0ddde6e84a0573c67aa))
* **execution:** make reruns create executions + improve logs; hide non-layer chart labels. ([e1c96e5](https://github.com/yuyash/auto-forex-web-service/commit/e1c96e55f5817d5b9272078a95be5fde75b870a2))
* **floor:** default momentum to candle lookback ([d5b5f9c](https://github.com/yuyash/auto-forex-web-service/commit/d5b5f9c17921938ff624a94ef849aaa1e01299dd))
* hedging and trend panel ([#85](https://github.com/yuyash/auto-forex-web-service/issues/85)) ([8743b6a](https://github.com/yuyash/auto-forex-web-service/commit/8743b6ac2edf51f429039edb705dcbd8a2555154))
* improve market task logging ([#100](https://github.com/yuyash/auto-forex-web-service/issues/100)) ([3512d2d](https://github.com/yuyash/auto-forex-web-service/commit/3512d2dbcf3ac9a85561f734d29b2e03bbf5e3a8))
* refresh token security ([#51](https://github.com/yuyash/auto-forex-web-service/issues/51)) ([4eb53b4](https://github.com/yuyash/auto-forex-web-service/commit/4eb53b4bd67af15ffa5a9d3a6fc695e28612058f))
* snowball strategy tab design ([#137](https://github.com/yuyash/auto-forex-web-service/issues/137)) ([ef21bc0](https://github.com/yuyash/auto-forex-web-service/commit/ef21bc0b3f97b40f70722f4d937c57de6b67a513))
* **strategy:** add display cycle splitting and OHLC chart visualization ([#179](https://github.com/yuyash/auto-forex-web-service/issues/179)) ([20f97ab](https://github.com/yuyash/auto-forex-web-service/commit/20f97ab49f1f48126bf51cd35118b511b98e7192))
* **trading:** add planned_exit_price_formula to strategy events and … ([#96](https://github.com/yuyash/auto-forex-web-service/issues/96)) ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** add planned_exit_price_formula to strategy events and improve mobile UI ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** add sequence_number to preserve event ordering within … ([#206](https://github.com/yuyash/auto-forex-web-service/issues/206)) ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))
* **trading:** add sequence_number to preserve event ordering within same tick ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))
* **trading:** enforce page/page_size pagination across logs & results endpoints ([2d66aad](https://github.com/yuyash/auto-forex-web-service/commit/2d66aad0f6b9b40f133fff5e5ae42388fbeb1f90))
* **trading:** improve trading system with enhanced events, positions, and UI components ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading system with enhanced events, positions… ([#91](https://github.com/yuyash/auto-forex-web-service/issues/91)) ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading UI and backend execution handling ([#93](https://github.com/yuyash/auto-forex-web-service/issues/93)) ([48ebe50](https://github.com/yuyash/auto-forex-web-service/commit/48ebe50cf5015546d37629ce32fa10b1f0011e46))
* **trading:** persist live execution artifacts + metrics checkpoints ([a6b8c8d](https://github.com/yuyash/auto-forex-web-service/commit/a6b8c8d1516a42b171b4dac8a688f489274eae88))
* **trading:** refactor app structure ([#21](https://github.com/yuyash/auto-forex-web-service/issues/21)) ([6e5db34](https://github.com/yuyash/auto-forex-web-service/commit/6e5db3461377af6596b6e1e5c6b8ce4c5df1eddb))


### Bug Fixes

* add version info ([#27](https://github.com/yuyash/auto-forex-web-service/issues/27)) ([b5217d1](https://github.com/yuyash/auto-forex-web-service/commit/b5217d16a4e476825b5521db9fe1d53c2fe9093a))
* api enhancement ([#40](https://github.com/yuyash/auto-forex-web-service/issues/40)) ([ab0b564](https://github.com/yuyash/auto-forex-web-service/commit/ab0b564dd6589279ed84556ba586d64e01dfb60d))
* **auth:** add AnonRateThrottle to protect unauthenticated endpoints ([#56](https://github.com/yuyash/auto-forex-web-service/issues/56)) ([ae490ce](https://github.com/yuyash/auto-forex-web-service/commit/ae490ce1128b01d2b143c90f98570adc8780dae1))
* **backtest:** make charts and markers robust ([25013aa](https://github.com/yuyash/auto-forex-web-service/commit/25013aa50742b17feb59d019843ac4a32d2b2f8c))
* celery task doesnt update the progress correctly. ([f14f3f2](https://github.com/yuyash/auto-forex-web-service/commit/f14f3f202d459ea599bea27ce89155b6a5e5db59))
* celery task race condition ([#31](https://github.com/yuyash/auto-forex-web-service/issues/31)) ([87b3354](https://github.com/yuyash/auto-forex-web-service/commit/87b33548f2cb0c52ad1aa4a2b250944ec8e707da))
* chart marker positions ([#197](https://github.com/yuyash/auto-forex-web-service/issues/197)) ([a9794a3](https://github.com/yuyash/auto-forex-web-service/commit/a9794a331f766c403e76d6e294c262943f8f4d66))
* **chart:** fixed an issue where OHLC chart doesn't follow the progre… ([#120](https://github.com/yuyash/auto-forex-web-service/issues/120)) ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** fixed an issue where OHLC chart doesn't follow the progress bar properly. ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** trading migration 0019 ([#116](https://github.com/yuyash/auto-forex-web-service/issues/116)) ([a8d9a4e](https://github.com/yuyash/auto-forex-web-service/commit/a8d9a4e7d931c2106f4b643bef05a70f6e7e133c))
* clear stale stream cache on startup ([cc65f57](https://github.com/yuyash/auto-forex-web-service/commit/cc65f57a8190bf7ab95151984b07515783eb959b))
* cycle based snowball strategy ([#188](https://github.com/yuyash/auto-forex-web-service/issues/188)) ([4cbd2be](https://github.com/yuyash/auto-forex-web-service/commit/4cbd2be327178526c0828d871bc77c43e31a05de))
* cycle id assignment and chart ([#190](https://github.com/yuyash/auto-forex-web-service/issues/190)) ([d3f7700](https://github.com/yuyash/auto-forex-web-service/commit/d3f77005565781c4b3629d3f12bfc3d9b542b9d4))
* **docker:** prevent prod config bind-mount shadowing Django settings. ([b3270b1](https://github.com/yuyash/auto-forex-web-service/commit/b3270b1b11bfd83869950037656d8cd752eb04ce))
* enforce frontend npm ci and override blocked react-is ([#46](https://github.com/yuyash/auto-forex-web-service/issues/46)) ([1f200b4](https://github.com/yuyash/auto-forex-web-service/commit/1f200b475d5bedc8de79256ec03b19f5a651c877))
* **floor-strategy:** reset retracement flag when price continues moving against position ([e88207b](https://github.com/yuyash/auto-forex-web-service/commit/e88207bc09c890e6f575696c7a49416048838caa))
* handle immutable ExecutionMetrics for trading tasks ([9a39233](https://github.com/yuyash/auto-forex-web-service/commit/9a392333e83ec398185ec5754a67825778c1f127))
* Handle new OANDA API message types for streaming ([47f7d25](https://github.com/yuyash/auto-forex-web-service/commit/47f7d2504b39648f87561f07483255229bbefa13))
* incremental polling reduce backend load ([#24](https://github.com/yuyash/auto-forex-web-service/issues/24)) ([980f163](https://github.com/yuyash/auto-forex-web-service/commit/980f1637145586a6955bfdb434532fcd1ed1b3e7))
* limit live results and strategy events to prevent 1GB+ JSON payloads ([61c4477](https://github.com/yuyash/auto-forex-web-service/commit/61c4477ea1f1fc846f08ea3207185e420c5a623e))
* **logging:** improve production logging ([#106](https://github.com/yuyash/auto-forex-web-service/issues/106)) ([06f2fdb](https://github.com/yuyash/auto-forex-web-service/commit/06f2fdb068dda50fba59a72312a3be4e11bf4940))
* **market-data:** use correct OANDA streaming hostname. ([af6e392](https://github.com/yuyash/auto-forex-web-service/commit/af6e39257d6a25f99bac766deeca239a318a39dc))
* **market:** dedupe TickData bulk upserts to avoid Postgres cardinality violation ([397a45c](https://github.com/yuyash/auto-forex-web-service/commit/397a45c44561af2636297d6b2b6295f35488b400))
* **metrics:** resolve overlay display and add viewport-driven fetching ([#114](https://github.com/yuyash/auto-forex-web-service/issues/114)) ([e87a285](https://github.com/yuyash/auto-forex-web-service/commit/e87a2855b4ccf087d42cf4d4f876a48c73737a24))
* **orders:** change broker_order_id from CharField(255) to TextField ([#104](https://github.com/yuyash/auto-forex-web-service/issues/104)) ([8f16ec6](https://github.com/yuyash/auto-forex-web-service/commit/8f16ec6a76955d4b4fc26488dfe75b71aaa78534))
* prevent retracement_limit_reached spam generating 167K+ events ([6c14968](https://github.com/yuyash/auto-forex-web-service/commit/6c149681e55eee083914f78a2acca8f625e3a2cc))
* read version from pyproject.toml instead of importlib.metadata ([#29](https://github.com/yuyash/auto-forex-web-service/issues/29)) ([8a8f986](https://github.com/yuyash/auto-forex-web-service/commit/8a8f986a5c5ae0433cb8c5ca24c339f13e4d29ad))
* reduce API rate limit pressure and lazy-load chart data ([#38](https://github.com/yuyash/auto-forex-web-service/issues/38)) ([e733834](https://github.com/yuyash/auto-forex-web-service/commit/e733834e6bf47bd144d98d9c526f5a5eceb19745))
* resolve all ty type checker errors and warnings ([#13](https://github.com/yuyash/auto-forex-web-service/issues/13)) ([1883525](https://github.com/yuyash/auto-forex-web-service/commit/1883525ce1fd5008b5c46d42e57d185620a78502))
* resolve backend code quality issues ([#160](https://github.com/yuyash/auto-forex-web-service/issues/160)) ([def2e22](https://github.com/yuyash/auto-forex-web-service/commit/def2e22766e4192779932619406516f10ffc42b6))
* resolve flake8, mypy, and pylint errors in floor strategy and task executor ([b2b9949](https://github.com/yuyash/auto-forex-web-service/commit/b2b9949c5408ccbc163fdf92abd249b55f0ca88d))
* **security:** remove unused UserSession.last_activity field ([#112](https://github.com/yuyash/auto-forex-web-service/issues/112)) ([3198e40](https://github.com/yuyash/auto-forex-web-service/commit/3198e40782bf16ffe27a35c5e04c53854fb6f068))
* snowball add count reset and tests ([#73](https://github.com/yuyash/auto-forex-web-service/issues/73)) ([847ffd9](https://github.com/yuyash/auto-forex-web-service/commit/847ffd9cef2929009549f418acfb95541d11ea97))
* stabilize rerun/status flow and fix floor trade PnL metrics ([d7f2325](https://github.com/yuyash/auto-forex-web-service/commit/d7f23254fef3c23c2f79e48732ef255f68ca6219))
* stabilize streams, logs, and backtest/trading results UI ([f6f15a2](https://github.com/yuyash/auto-forex-web-service/commit/f6f15a241fda3c57ca995472e6de429e64b63ef5))
* strategy events root entry id default ([#163](https://github.com/yuyash/auto-forex-web-service/issues/163)) ([523e8a6](https://github.com/yuyash/auto-forex-web-service/commit/523e8a6ab3162e2eef92be0e2002f89c232d3e48))
* strategy grouping parent chain ([#175](https://github.com/yuyash/auto-forex-web-service/issues/175)) ([19461d6](https://github.com/yuyash/auto-forex-web-service/commit/19461d62e3d0329d3d3360142eb206b8ee9ff944))
* **strategy:** correct snowball counter lot sizing and add retracemen… ([#87](https://github.com/yuyash/auto-forex-web-service/issues/87)) ([804e7d1](https://github.com/yuyash/auto-forex-web-service/commit/804e7d15754e8a6310dd3a03201ed805b1f327f2))
* **strategy:** DB fallback for cycle_id, granularity selector, chart … ([#204](https://github.com/yuyash/auto-forex-web-service/issues/204)) ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))
* **strategy:** DB fallback for cycle_id, granularity selector, chart fixes ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))
* **strategy:** guard m_pips range validation behind dynamic_tp_enable… ([#81](https://github.com/yuyash/auto-forex-web-service/issues/81)) ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** guard m_pips range validation behind dynamic_tp_enabled and raise m_pips_max default ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** normalize atr_timeframe to uppercase and add snowball … ([#75](https://github.com/yuyash/auto-forex-web-service/issues/75)) ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **strategy:** normalize atr_timeframe to uppercase and add snowball tests ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **strategy:** trigger deployment for cycle-based snowball refactor ([#182](https://github.com/yuyash/auto-forex-web-service/issues/182)) ([13f6bc4](https://github.com/yuyash/auto-forex-web-service/commit/13f6bc43549cb8b1d359516a8c9590df142c9306))
* **tests:** update expected hostnames for streaming tests ([cbaa7a2](https://github.com/yuyash/auto-forex-web-service/commit/cbaa7a27039043ae9687813829ced34e0ccf33fe))
* **trading:** trading task creation ([#125](https://github.com/yuyash/auto-forex-web-service/issues/125)) ([74f1dbd](https://github.com/yuyash/auto-forex-web-service/commit/74f1dbd177acef2936fd8d0a1245c93c58a84be2))
* **trading:** use pure arithmetic in planned_exit_price_formula ([#98](https://github.com/yuyash/auto-forex-web-service/issues/98)) ([0b5edbd](https://github.com/yuyash/auto-forex-web-service/commit/0b5edbdeb05c6fc0fab1be041bbee75fb4cc3011))
* trigger deployment ([#169](https://github.com/yuyash/auto-forex-web-service/issues/169)) ([9d3cafd](https://github.com/yuyash/auto-forex-web-service/commit/9d3cafd7bbcfea767429c7313dceb9a0e33806bc))
* Use decrypted API token for OANDA streaming connections ([aa9ead5](https://github.com/yuyash/auto-forex-web-service/commit/aa9ead51e80b0930655e71f54b60f5dba5c0bbd9))
* vscode settings warnings ([#134](https://github.com/yuyash/auto-forex-web-service/issues/134)) ([c55842d](https://github.com/yuyash/auto-forex-web-service/commit/c55842d4b25147605c7e480afe08a2259d6cf728))

## [1.17.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.5...backend-v1.17.0) (2026-03-26)


### Features

* **trading:** add sequence_number to preserve event ordering within … ([#206](https://github.com/yuyash/auto-forex-web-service/issues/206)) ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))
* **trading:** add sequence_number to preserve event ordering within same tick ([31f686e](https://github.com/yuyash/auto-forex-web-service/commit/31f686ead46296962ef7fa849ed9ff90afee4746))

## [1.16.5](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.4...backend-v1.16.5) (2026-03-26)


### Bug Fixes

* **strategy:** DB fallback for cycle_id, granularity selector, chart … ([#204](https://github.com/yuyash/auto-forex-web-service/issues/204)) ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))
* **strategy:** DB fallback for cycle_id, granularity selector, chart fixes ([794a7cc](https://github.com/yuyash/auto-forex-web-service/commit/794a7cc1911528b910fc953b0c126d7023db6567))

## [1.16.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.3...backend-v1.16.4) (2026-03-26)


### Bug Fixes

* chart marker positions ([#197](https://github.com/yuyash/auto-forex-web-service/issues/197)) ([a9794a3](https://github.com/yuyash/auto-forex-web-service/commit/a9794a331f766c403e76d6e294c262943f8f4d66))

## [1.16.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.2...backend-v1.16.3) (2026-03-25)


### Bug Fixes

* cycle id assignment and chart ([#190](https://github.com/yuyash/auto-forex-web-service/issues/190)) ([d3f7700](https://github.com/yuyash/auto-forex-web-service/commit/d3f77005565781c4b3629d3f12bfc3d9b542b9d4))

## [1.16.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.1...backend-v1.16.2) (2026-03-25)


### Bug Fixes

* cycle based snowball strategy ([#188](https://github.com/yuyash/auto-forex-web-service/issues/188)) ([4cbd2be](https://github.com/yuyash/auto-forex-web-service/commit/4cbd2be327178526c0828d871bc77c43e31a05de))

## [1.16.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.16.0...backend-v1.16.1) (2026-03-25)


### Bug Fixes

* **strategy:** trigger deployment for cycle-based snowball refactor ([#182](https://github.com/yuyash/auto-forex-web-service/issues/182)) ([13f6bc4](https://github.com/yuyash/auto-forex-web-service/commit/13f6bc43549cb8b1d359516a8c9590df142c9306))

## [1.16.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.15.4...backend-v1.16.0) (2026-03-24)


### Features

* **strategy:** add display cycle splitting and OHLC chart visualization ([#179](https://github.com/yuyash/auto-forex-web-service/issues/179)) ([20f97ab](https://github.com/yuyash/auto-forex-web-service/commit/20f97ab49f1f48126bf51cd35118b511b98e7192))

## [1.15.4](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.15.3...backend-v1.15.4) (2026-03-24)


### Bug Fixes

* strategy grouping parent chain ([#175](https://github.com/yuyash/auto-forex-web-service/issues/175)) ([19461d6](https://github.com/yuyash/auto-forex-web-service/commit/19461d62e3d0329d3d3360142eb206b8ee9ff944))

## [1.15.3](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.15.2...backend-v1.15.3) (2026-03-24)


### Bug Fixes

* trigger deployment ([#169](https://github.com/yuyash/auto-forex-web-service/issues/169)) ([9d3cafd](https://github.com/yuyash/auto-forex-web-service/commit/9d3cafd7bbcfea767429c7313dceb9a0e33806bc))

## [1.15.2](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.15.1...backend-v1.15.2) (2026-03-24)


### Bug Fixes

* strategy events root entry id default ([#163](https://github.com/yuyash/auto-forex-web-service/issues/163)) ([523e8a6](https://github.com/yuyash/auto-forex-web-service/commit/523e8a6ab3162e2eef92be0e2002f89c232d3e48))

## [1.15.1](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.15.0...backend-v1.15.1) (2026-03-24)


### Bug Fixes

* resolve backend code quality issues ([#160](https://github.com/yuyash/auto-forex-web-service/issues/160)) ([def2e22](https://github.com/yuyash/auto-forex-web-service/commit/def2e22766e4192779932619406516f10ffc42b6))

## [1.15.0](https://github.com/yuyash/auto-forex-web-service/compare/backend-v1.14.6...backend-v1.15.0) (2026-03-23)


### Features

* Add --role-arn option to load-data command. ([a1c3a47](https://github.com/yuyash/auto-forex-web-service/commit/a1c3a47c963cf6780ea675a5baad04023c1e0e0f))
* add backtest export button and realized/unrealized P&L metrics to results tab ([6752c14](https://github.com/yuyash/auto-forex-web-service/commit/6752c14c30940641924703a6ad4ef0dac9064aed))
* add management commands for backtest, trading, and config CRUD … ([#54](https://github.com/yuyash/auto-forex-web-service/issues/54)) ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* add management commands for backtest, trading, and config CRUD operations ([fc4c4ee](https://github.com/yuyash/auto-forex-web-service/commit/fc4c4ee6d3ddf86daefc73eda090fb95ef2e6ae5))
* Add pip_size and instrument fields to backtest tasks and fix UI… ([#16](https://github.com/yuyash/auto-forex-web-service/issues/16)) ([5a71b6b](https://github.com/yuyash/auto-forex-web-service/commit/5a71b6b1ef624dc4367e224af29f4ca8e93d63ae))
* add snowball strategy ([#69](https://github.com/yuyash/auto-forex-web-service/issues/69)) ([e43eaef](https://github.com/yuyash/auto-forex-web-service/commit/e43eaefacd5a339b657a9e6348d3cc7f039019c0))
* add strategy defaults API and configuration UX improvements ([c69ce85](https://github.com/yuyash/auto-forex-web-service/commit/c69ce8558337f2af7f49a459d5fb5f61970768fe))
* add task summary API and migrate detail views to unified summary ([#35](https://github.com/yuyash/auto-forex-web-service/issues/35)) ([09e7bd8](https://github.com/yuyash/auto-forex-web-service/commit/09e7bd8112a7c67ad3186f25e47035368fae5975))
* add unified task results API + migrate UI; normalize equity curve ([b17367a](https://github.com/yuyash/auto-forex-web-service/commit/b17367abbff41483799c2d37a1dfbad9eb8500bc))
* **api:** migrate task execution APIs to execution_run_id ([#44](https://github.com/yuyash/auto-forex-web-service/issues/44)) ([b0d5332](https://github.com/yuyash/auto-forex-web-service/commit/b0d5332a5069aaa1fe038151926302f0485cf6be))
* **auth:** surface whitelist-blocked login failures ([64d7392](https://github.com/yuyash/auto-forex-web-service/commit/64d7392bee2645de932e7e39dd67211ec5580db5))
* auto-resume trading tasks on worker startup ([c1a1ce0](https://github.com/yuyash/auto-forex-web-service/commit/c1a1ce0dda811ebd3c9f22dec06aedb114f12258))
* celery resilience recovery ([#42](https://github.com/yuyash/auto-forex-web-service/issues/42)) ([dfd0f3f](https://github.com/yuyash/auto-forex-web-service/commit/dfd0f3fb5bdfd271927356d3bd07307adea27d55))
* **celery:** db backup s3 ([#154](https://github.com/yuyash/auto-forex-web-service/issues/154)) ([241bae4](https://github.com/yuyash/auto-forex-web-service/commit/241bae421ef664159a99245f963eeae879b9a400))
* event scope queue refactor ([#48](https://github.com/yuyash/auto-forex-web-service/issues/48)) ([220238c](https://github.com/yuyash/auto-forex-web-service/commit/220238c7497cb7f0602c1ba3b7d567bd3c657d29))
* **events:** enforce 1:1 canonical floor strategy events across backend+frontend ([4af619a](https://github.com/yuyash/auto-forex-web-service/commit/4af619a14a102916aad7a0ddde6e84a0573c67aa))
* **execution:** make reruns create executions + improve logs; hide non-layer chart labels. ([e1c96e5](https://github.com/yuyash/auto-forex-web-service/commit/e1c96e55f5817d5b9272078a95be5fde75b870a2))
* **floor:** default momentum to candle lookback ([d5b5f9c](https://github.com/yuyash/auto-forex-web-service/commit/d5b5f9c17921938ff624a94ef849aaa1e01299dd))
* hedging and trend panel ([#85](https://github.com/yuyash/auto-forex-web-service/issues/85)) ([8743b6a](https://github.com/yuyash/auto-forex-web-service/commit/8743b6ac2edf51f429039edb705dcbd8a2555154))
* improve market task logging ([#100](https://github.com/yuyash/auto-forex-web-service/issues/100)) ([3512d2d](https://github.com/yuyash/auto-forex-web-service/commit/3512d2dbcf3ac9a85561f734d29b2e03bbf5e3a8))
* refresh token security ([#51](https://github.com/yuyash/auto-forex-web-service/issues/51)) ([4eb53b4](https://github.com/yuyash/auto-forex-web-service/commit/4eb53b4bd67af15ffa5a9d3a6fc695e28612058f))
* snowball strategy tab design ([#137](https://github.com/yuyash/auto-forex-web-service/issues/137)) ([ef21bc0](https://github.com/yuyash/auto-forex-web-service/commit/ef21bc0b3f97b40f70722f4d937c57de6b67a513))
* **trading:** add planned_exit_price_formula to strategy events and … ([#96](https://github.com/yuyash/auto-forex-web-service/issues/96)) ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** add planned_exit_price_formula to strategy events and improve mobile UI ([13c0a1b](https://github.com/yuyash/auto-forex-web-service/commit/13c0a1b3263f4b01a2d578bf7e21edda67afaebd))
* **trading:** enforce page/page_size pagination across logs & results endpoints ([2d66aad](https://github.com/yuyash/auto-forex-web-service/commit/2d66aad0f6b9b40f133fff5e5ae42388fbeb1f90))
* **trading:** improve trading system with enhanced events, positions, and UI components ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading system with enhanced events, positions… ([#91](https://github.com/yuyash/auto-forex-web-service/issues/91)) ([a356dad](https://github.com/yuyash/auto-forex-web-service/commit/a356dad5618639968719328f4ae257e843568838))
* **trading:** improve trading UI and backend execution handling ([#93](https://github.com/yuyash/auto-forex-web-service/issues/93)) ([48ebe50](https://github.com/yuyash/auto-forex-web-service/commit/48ebe50cf5015546d37629ce32fa10b1f0011e46))
* **trading:** persist live execution artifacts + metrics checkpoints ([a6b8c8d](https://github.com/yuyash/auto-forex-web-service/commit/a6b8c8d1516a42b171b4dac8a688f489274eae88))
* **trading:** refactor app structure ([#21](https://github.com/yuyash/auto-forex-web-service/issues/21)) ([6e5db34](https://github.com/yuyash/auto-forex-web-service/commit/6e5db3461377af6596b6e1e5c6b8ce4c5df1eddb))


### Bug Fixes

* add version info ([#27](https://github.com/yuyash/auto-forex-web-service/issues/27)) ([b5217d1](https://github.com/yuyash/auto-forex-web-service/commit/b5217d16a4e476825b5521db9fe1d53c2fe9093a))
* api enhancement ([#40](https://github.com/yuyash/auto-forex-web-service/issues/40)) ([ab0b564](https://github.com/yuyash/auto-forex-web-service/commit/ab0b564dd6589279ed84556ba586d64e01dfb60d))
* **auth:** add AnonRateThrottle to protect unauthenticated endpoints ([#56](https://github.com/yuyash/auto-forex-web-service/issues/56)) ([ae490ce](https://github.com/yuyash/auto-forex-web-service/commit/ae490ce1128b01d2b143c90f98570adc8780dae1))
* **backtest:** make charts and markers robust ([25013aa](https://github.com/yuyash/auto-forex-web-service/commit/25013aa50742b17feb59d019843ac4a32d2b2f8c))
* celery task doesnt update the progress correctly. ([f14f3f2](https://github.com/yuyash/auto-forex-web-service/commit/f14f3f202d459ea599bea27ce89155b6a5e5db59))
* celery task race condition ([#31](https://github.com/yuyash/auto-forex-web-service/issues/31)) ([87b3354](https://github.com/yuyash/auto-forex-web-service/commit/87b33548f2cb0c52ad1aa4a2b250944ec8e707da))
* **chart:** fixed an issue where OHLC chart doesn't follow the progre… ([#120](https://github.com/yuyash/auto-forex-web-service/issues/120)) ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** fixed an issue where OHLC chart doesn't follow the progress bar properly. ([777df1c](https://github.com/yuyash/auto-forex-web-service/commit/777df1c423701179c8b79f96ed1b1575de8cd844))
* **chart:** trading migration 0019 ([#116](https://github.com/yuyash/auto-forex-web-service/issues/116)) ([a8d9a4e](https://github.com/yuyash/auto-forex-web-service/commit/a8d9a4e7d931c2106f4b643bef05a70f6e7e133c))
* clear stale stream cache on startup ([cc65f57](https://github.com/yuyash/auto-forex-web-service/commit/cc65f57a8190bf7ab95151984b07515783eb959b))
* **docker:** prevent prod config bind-mount shadowing Django settings. ([b3270b1](https://github.com/yuyash/auto-forex-web-service/commit/b3270b1b11bfd83869950037656d8cd752eb04ce))
* enforce frontend npm ci and override blocked react-is ([#46](https://github.com/yuyash/auto-forex-web-service/issues/46)) ([1f200b4](https://github.com/yuyash/auto-forex-web-service/commit/1f200b475d5bedc8de79256ec03b19f5a651c877))
* **floor-strategy:** reset retracement flag when price continues moving against position ([e88207b](https://github.com/yuyash/auto-forex-web-service/commit/e88207bc09c890e6f575696c7a49416048838caa))
* handle immutable ExecutionMetrics for trading tasks ([9a39233](https://github.com/yuyash/auto-forex-web-service/commit/9a392333e83ec398185ec5754a67825778c1f127))
* Handle new OANDA API message types for streaming ([47f7d25](https://github.com/yuyash/auto-forex-web-service/commit/47f7d2504b39648f87561f07483255229bbefa13))
* incremental polling reduce backend load ([#24](https://github.com/yuyash/auto-forex-web-service/issues/24)) ([980f163](https://github.com/yuyash/auto-forex-web-service/commit/980f1637145586a6955bfdb434532fcd1ed1b3e7))
* limit live results and strategy events to prevent 1GB+ JSON payloads ([61c4477](https://github.com/yuyash/auto-forex-web-service/commit/61c4477ea1f1fc846f08ea3207185e420c5a623e))
* **logging:** improve production logging ([#106](https://github.com/yuyash/auto-forex-web-service/issues/106)) ([06f2fdb](https://github.com/yuyash/auto-forex-web-service/commit/06f2fdb068dda50fba59a72312a3be4e11bf4940))
* **market-data:** use correct OANDA streaming hostname. ([af6e392](https://github.com/yuyash/auto-forex-web-service/commit/af6e39257d6a25f99bac766deeca239a318a39dc))
* **market:** dedupe TickData bulk upserts to avoid Postgres cardinality violation ([397a45c](https://github.com/yuyash/auto-forex-web-service/commit/397a45c44561af2636297d6b2b6295f35488b400))
* **metrics:** resolve overlay display and add viewport-driven fetching ([#114](https://github.com/yuyash/auto-forex-web-service/issues/114)) ([e87a285](https://github.com/yuyash/auto-forex-web-service/commit/e87a2855b4ccf087d42cf4d4f876a48c73737a24))
* **orders:** change broker_order_id from CharField(255) to TextField ([#104](https://github.com/yuyash/auto-forex-web-service/issues/104)) ([8f16ec6](https://github.com/yuyash/auto-forex-web-service/commit/8f16ec6a76955d4b4fc26488dfe75b71aaa78534))
* prevent retracement_limit_reached spam generating 167K+ events ([6c14968](https://github.com/yuyash/auto-forex-web-service/commit/6c149681e55eee083914f78a2acca8f625e3a2cc))
* read version from pyproject.toml instead of importlib.metadata ([#29](https://github.com/yuyash/auto-forex-web-service/issues/29)) ([8a8f986](https://github.com/yuyash/auto-forex-web-service/commit/8a8f986a5c5ae0433cb8c5ca24c339f13e4d29ad))
* reduce API rate limit pressure and lazy-load chart data ([#38](https://github.com/yuyash/auto-forex-web-service/issues/38)) ([e733834](https://github.com/yuyash/auto-forex-web-service/commit/e733834e6bf47bd144d98d9c526f5a5eceb19745))
* resolve all ty type checker errors and warnings ([#13](https://github.com/yuyash/auto-forex-web-service/issues/13)) ([1883525](https://github.com/yuyash/auto-forex-web-service/commit/1883525ce1fd5008b5c46d42e57d185620a78502))
* resolve flake8, mypy, and pylint errors in floor strategy and task executor ([b2b9949](https://github.com/yuyash/auto-forex-web-service/commit/b2b9949c5408ccbc163fdf92abd249b55f0ca88d))
* **security:** remove unused UserSession.last_activity field ([#112](https://github.com/yuyash/auto-forex-web-service/issues/112)) ([3198e40](https://github.com/yuyash/auto-forex-web-service/commit/3198e40782bf16ffe27a35c5e04c53854fb6f068))
* snowball add count reset and tests ([#73](https://github.com/yuyash/auto-forex-web-service/issues/73)) ([847ffd9](https://github.com/yuyash/auto-forex-web-service/commit/847ffd9cef2929009549f418acfb95541d11ea97))
* stabilize rerun/status flow and fix floor trade PnL metrics ([d7f2325](https://github.com/yuyash/auto-forex-web-service/commit/d7f23254fef3c23c2f79e48732ef255f68ca6219))
* stabilize streams, logs, and backtest/trading results UI ([f6f15a2](https://github.com/yuyash/auto-forex-web-service/commit/f6f15a241fda3c57ca995472e6de429e64b63ef5))
* **strategy:** correct snowball counter lot sizing and add retracemen… ([#87](https://github.com/yuyash/auto-forex-web-service/issues/87)) ([804e7d1](https://github.com/yuyash/auto-forex-web-service/commit/804e7d15754e8a6310dd3a03201ed805b1f327f2))
* **strategy:** guard m_pips range validation behind dynamic_tp_enable… ([#81](https://github.com/yuyash/auto-forex-web-service/issues/81)) ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** guard m_pips range validation behind dynamic_tp_enabled and raise m_pips_max default ([b77df30](https://github.com/yuyash/auto-forex-web-service/commit/b77df30723c2fe1852601fb0c6198a8cdf428905))
* **strategy:** normalize atr_timeframe to uppercase and add snowball … ([#75](https://github.com/yuyash/auto-forex-web-service/issues/75)) ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **strategy:** normalize atr_timeframe to uppercase and add snowball tests ([2c7995c](https://github.com/yuyash/auto-forex-web-service/commit/2c7995c50ad7582732cbcbfb1ec3efa559b6405c))
* **tests:** update expected hostnames for streaming tests ([cbaa7a2](https://github.com/yuyash/auto-forex-web-service/commit/cbaa7a27039043ae9687813829ced34e0ccf33fe))
* **trading:** trading task creation ([#125](https://github.com/yuyash/auto-forex-web-service/issues/125)) ([74f1dbd](https://github.com/yuyash/auto-forex-web-service/commit/74f1dbd177acef2936fd8d0a1245c93c58a84be2))
* **trading:** use pure arithmetic in planned_exit_price_formula ([#98](https://github.com/yuyash/auto-forex-web-service/issues/98)) ([0b5edbd](https://github.com/yuyash/auto-forex-web-service/commit/0b5edbdeb05c6fc0fab1be041bbee75fb4cc3011))
* Use decrypted API token for OANDA streaming connections ([aa9ead5](https://github.com/yuyash/auto-forex-web-service/commit/aa9ead51e80b0930655e71f54b60f5dba5c0bbd9))
* vscode settings warnings ([#134](https://github.com/yuyash/auto-forex-web-service/issues/134)) ([c55842d](https://github.com/yuyash/auto-forex-web-service/commit/c55842d4b25147605c7e480afe08a2259d6cf728))
