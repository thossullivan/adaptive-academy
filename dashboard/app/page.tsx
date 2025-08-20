import Link from 'next/link';

interface NavCard {
  title: string;
  description: string;
  href: string;
  icon: string;
}

const navigationCards: NavCard[] = [
  {
    title: 'My Courses',
    description: 'Access your enrolled courses and track your progress',
    href: '/courses',
    icon: '📚'
  },
  {
    title: 'Learning Path',
    description: 'View your personalized learning journey',
    href: '/learning-path',
    icon: '🎯'
  },
  {
    title: 'Progress Stats',
    description: 'Check your learning statistics and achievements',
    href: '/stats',
    icon: '📊'
  },
  {
    title: 'Resources',
    description: 'Access additional learning materials and resources',
    href: '/resources',
    icon: '📑'
  }
];

export default function HomePage() {
  return (
    <main className="min-h-screen p-6 md:p-12">
      {/* Welcome Section */}
      <section className="mb-12">
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-4">
          Welcome to Your Learning Dashboard
        </h1>
        <p className="text-xl text-gray-600">
          Track your progress, access courses, and continue your learning journey.
        </p>
      </section>

      {/* Navigation Cards Grid */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {navigationCards.map((card) => (
          <Link
            key={card.title}
            href={card.href}
            className="block p-6 bg-white rounded-lg shadow-md hover:shadow-lg transition-shadow duration-300 border border-gray-100"
          >
            <div className="flex flex-col h-full">
              <div className="text-3xl mb-4">{card.icon}</div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                {card.title}
              </h2>
              <p className="text-gray-600 flex-grow">
                {card.description}
              </p>
            </div>
          </Link>
        ))}
      </section>

      {/* Quick Stats Section */}
      <section className="mt-12 p-6 bg-gray-50 rounded-lg">
        <h2 className="text-2xl font-semibold text-gray-900 mb-4">
          Quick Overview
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="bg-white p-4 rounded-md shadow-sm">
            <p className="text-gray-600">Courses in Progress</p>
            <p className="text-2xl font-bold text-gray-900">3</p>
          </div>
          <div className="bg-white p-4 rounded-md shadow-sm">
            <p className="text-gray-600">Completed Courses</p>
            <p className="text-2xl font-bold text-gray-900">7</p>
          </div>
          <div className="bg-white p-4 rounded-md shadow-sm">
            <p className="text-gray-600">Achievement Points</p>
            <p className="text-2xl font-bold text-gray-900">850</p>
          </div>
        </div>
      </section>
    </main>
  );
}